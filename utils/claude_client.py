from __future__ import annotations

import os
import time
import anthropic
from dotenv import load_dotenv

load_dotenv()

# Lazy client: only created when first API call is made.
# This allows --mock mode to work without an API key.
_client = None

_mock_mode = False

MODELS = {
    "analysis": "claude-sonnet-4-6",
    "lightweight": "claude-haiku-4-5-20251001",
}

# Mock responses keyed by expected section headers in agent parsers.
_MOCK_RESPONSES = {
    "ta": (
        "ANALYSIS:\n"
        "Entry zone: $185.00-$187.50\n"
        "Target 1 (T1): $195.00\n"
        "Target 2 (T2): $205.00\n"
        "Stop loss: $180.00\n"
        "R:R ratio: 2.5:1\n\n"
        "The stock is consolidating near its 20-day EMA with rising volume, "
        "suggesting a breakout setup. RSI is neutral at 52, leaving room to run. "
        "ADX at 28 confirms a developing trend. The risk/reward is favorable "
        "given the clear support at the 50-day EMA.\n\n"
        "REASONING RECORD:\n"
        "[MOCK] This is a simulated reasoning record for pipeline testing. "
        "No real analysis was performed. In production, this section would "
        "contain the explicit logic behind the recommendation, memory context "
        "that influenced the decision, risks considered, and failure conditions."
    ),
    "sentiment": (
        "SENTIMENT:\n"
        "Score: +2\n"
        "Summary: Moderately bullish sentiment driven by strong earnings guidance "
        "and sector tailwinds. No major negative catalysts on the horizon.\n"
        "Key factors:\n"
        "- Recent earnings beat expectations by 8%\n"
        "- Sector rotation favoring tech/growth names\n"
        "- Analyst upgrades from two major banks\n"
        "Catalysts ahead:\n"
        "- Fed meeting next week could shift risk appetite\n"
        "- Product launch event in 10 days\n\n"
        "REASONING RECORD:\n"
        "[MOCK] This is a simulated sentiment reasoning record. "
        "Score of +2 reflects mildly positive news flow without strong conviction. "
        "In production, this would detail which news items carried the most weight."
    ),
    "portfolio": (
        "PORTFOLIO ASSESSMENT:\n"
        "No active holdings to assess. Portfolio is in cash. "
        "Market regime and VIX levels are within normal parameters. "
        "No overnight risk concerns.\n\n"
        "REASONING RECORD:\n"
        "[MOCK] This is a simulated portfolio assessment. "
        "With no holdings, the primary recommendation is to focus on "
        "new setups identified by the scanner and TA agents."
    ),
}


def set_mock_mode(enabled: bool) -> None:
    """Enable or disable mock mode. When enabled, no API calls are made."""
    global _mock_mode
    _mock_mode = enabled


def _get_client() -> anthropic.Anthropic:
    """Lazy-initialize the Anthropic client on first real API call."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def _pick_mock_response(system_prompt: str) -> str:
    """Select the appropriate mock response based on the system prompt content."""
    prompt_lower = system_prompt.lower()
    if "technical analyst" in prompt_lower:
        return _MOCK_RESPONSES["ta"]
    elif "sentiment analyst" in prompt_lower:
        return _MOCK_RESPONSES["sentiment"]
    elif "portfolio risk" in prompt_lower:
        return _MOCK_RESPONSES["portfolio"]
    # Fallback: return TA mock
    return _MOCK_RESPONSES["ta"]


def call(
    system_prompt: str,
    user_message: str,
    model: str = "analysis",
    max_tokens: int = 2000,
    cache_system: bool = True,
) -> str:
    """
    Single synchronous Claude API call.
    model: "analysis" (Sonnet) or "lightweight" (Haiku)
    cache_system: enables prompt caching on system prompt (90% savings on repeat reads)
    """
    if _mock_mode:
        return _pick_mock_response(system_prompt)

    model_id = MODELS.get(model, MODELS["analysis"])
    client = _get_client()

    # Build system with optional cache control
    system_content = [{"type": "text", "text": system_prompt}]
    if cache_system:
        system_content[0]["cache_control"] = {"type": "ephemeral"}

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                system=system_content,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            wait = 2 ** attempt * 5  # 5s, 10s, 20s
            time.sleep(wait)
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)
    raise RuntimeError("Claude API call failed after 3 attempts")


def call_with_cached_context(
    system_prompt: str,
    cached_context: str,
    live_query: str,
    model: str = "analysis",
    max_tokens: int = 2000,
) -> str:
    """
    Two-part user message: cached_context is marked for caching (slow-changing
    memory), live_query is fresh data. Use for TA and sentiment calls where
    ticker memory is read many times but today's data changes daily.
    """
    if _mock_mode:
        return _pick_mock_response(system_prompt)

    model_id = MODELS.get(model, MODELS["analysis"])
    client = _get_client()
    system_content = [{"type": "text", "text": system_prompt,
                        "cache_control": {"type": "ephemeral"}}]

    user_content = [
        {
            "type": "text",
            "text": cached_context,
            "cache_control": {"type": "ephemeral"},  # cache the memory context
        },
        {
            "type": "text",
            "text": live_query,  # today's fresh data, not cached
        },
    ]

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                system=system_content,
                messages=[{"role": "user", "content": user_content}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            wait = 2 ** attempt * 5
            time.sleep(wait)
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)
    raise RuntimeError("Claude API call failed after 3 attempts")


def call_batch(requests: list[dict]) -> dict[str, str]:
    """
    Async batch API call, 50% cost reduction.
    Use for: EOD outcome analysis, weekly learning loop.
    requests: list of {"custom_id": str, "system": str, "user": str, "model": str}
    Returns: dict of {custom_id: response_text}
    Blocks until complete (polls every 60s, max 24h).
    """
    if _mock_mode:
        return {r["custom_id"]: _pick_mock_response(r["system"]) for r in requests}

    client = _get_client()
    batch_requests = [
        {
            "custom_id": r["custom_id"],
            "params": {
                "model": MODELS.get(r.get("model", "analysis")),
                "max_tokens": r.get("max_tokens", 2000),
                "system": r["system"],
                "messages": [{"role": "user", "content": r["user"]}],
            },
        }
        for r in requests
    ]

    batch = client.messages.batches.create(requests=batch_requests)

    while True:
        status = client.messages.batches.retrieve(batch.id)
        if status.processing_status == "ended":
            break
        time.sleep(60)

    results = {}
    for result in client.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            results[result.custom_id] = result.result.message.content[0].text
        else:
            results[result.custom_id] = ""
    return results
