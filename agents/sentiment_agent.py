"""
Sentiment agent: news and sentiment synthesis for ticker analysis.

Uses call_with_cached_context() to separate memory from live news data.
Model tier: analysis (Sonnet) for sentiment synthesis.
"""

from __future__ import annotations

import logging
from datetime import datetime

from agents import memory_agent as mem
from utils import claude_client, data_fetcher
from utils.context_builder import build_sentiment_context
from ui import events

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a sentiment analyst monitoring news and market chatter for US equities,
ETFs, and Canadian stocks held in a personal investment portfolio.

Analyze the provided news and context to produce a sentiment assessment.

Your response must contain exactly two sections:

SENTIMENT:
Score: (integer -5 to +5, where -5 is extremely bearish, 0 is neutral, +5 is extremely bullish)
Summary: (2-3 sentences on what the news means for this ticker's 1-2 week outlook)
Key factors: (bullet list of the most impactful news items and their direction)
Catalysts ahead: (any upcoming events that could shift sentiment)

REASONING RECORD:
Why you scored sentiment as you did. Which news items carried the most weight.
What you are uncertain about. How this compares to any prior sentiment context
you were given. What would change your assessment."""


def analyze(
    ticker: str,
    regime: str,
) -> tuple[dict, str]:
    """
    Run sentiment analysis on a single ticker.

    Returns:
        (sentiment_dict, reasoning_record)
        sentiment_dict: {ticker, score, summary, key_factors}
        reasoning_record: Claude's reasoning
    """
    events.agent_state("sent", "active")
    events.log("sent", f"Sentiment analysis: {ticker}")

    # Fetch news
    news = data_fetcher.get_news(ticker)
    if not news:
        events.agent_state("sent", "done")
        return {"ticker": ticker, "score": 0, "summary": "No news available"}, "No news data to analyze."

    # Build context
    cached_context = build_sentiment_context(ticker)

    # Format live news
    news_lines = [f"## Recent news for {ticker} (as of {datetime.now().strftime('%Y-%m-%d')})"]
    news_lines.append(f"Current regime: {regime}\n")
    for i, item in enumerate(news, 1):
        news_lines.append(f"{i}. **{item['title']}**")
        if item.get("summary"):
            news_lines.append(f"   {item['summary'][:300]}")
        if item.get("published"):
            news_lines.append(f"   Published: {item['published']}")
        news_lines.append("")
    live_query = "\n".join(news_lines)

    events.packet("mem", "sent", "#F4A261")

    try:
        response = claude_client.call_with_cached_context(
            system_prompt=SYSTEM_PROMPT,
            cached_context=cached_context,
            live_query=live_query,
            model="lightweight",
            max_tokens=800,
        )
    except Exception as e:
        logger.error(f"Sentiment agent Claude call failed for {ticker}: {e}")
        events.agent_state("sent", "error")
        return {"ticker": ticker, "score": 0, "summary": f"API error: {e}"}, str(e)

    # Parse response
    sentiment_dict = {"ticker": ticker, "score": 0, "summary": "", "key_factors": ""}
    reasoning_record = ""

    if "SENTIMENT:" in response and "REASONING RECORD:" in response:
        sent_section = response.split("REASONING RECORD:")[0].split("SENTIMENT:")[-1].strip()
        reasoning_record = response.split("REASONING RECORD:")[-1].strip()

        # Extract score
        for line in sent_section.split("\n"):
            line_stripped = line.strip().lower()
            if line_stripped.startswith("score:"):
                try:
                    score_text = line_stripped.replace("score:", "").strip()
                    # Handle formats like "+3", "3", "-2"
                    score_num = int(score_text.split()[0].replace("+", ""))
                    sentiment_dict["score"] = max(-5, min(5, score_num))
                except (ValueError, IndexError):
                    pass
            elif line_stripped.startswith("summary:"):
                sentiment_dict["summary"] = line.strip()[8:].strip()

        sentiment_dict["full_analysis"] = sent_section
    else:
        reasoning_record = response
        sentiment_dict["summary"] = response[:500]

    # Save to ticker knowledge
    mem.save_reasoning_record("sentiment_agent", ticker, reasoning_record[:2000])

    # Update sentiment notes
    try:
        mem.upsert_ticker_knowledge(ticker, "", {
            "sentiment_notes": f"[{datetime.now().date().isoformat()}] Score: {sentiment_dict['score']}, {sentiment_dict['summary'][:200]}"
        })
    except Exception as e:
        logger.error(f"Failed to save sentiment notes for {ticker}: {e}")

    events.packet("sent", "mem", "#E8A87C")
    events.agent_state("sent", "done")
    return sentiment_dict, reasoning_record


def analyze_batch(
    tickers: list[str],
    regime: str,
) -> tuple[dict[str, dict], str]:
    """
    Analyze sentiment for multiple tickers.

    Returns:
        (results_dict, combined_reasoning)
        results_dict: {ticker: sentiment_dict}
    """
    results = {}
    all_reasoning = []

    for ticker in tickers:
        sentiment, reasoning = analyze(ticker, regime)
        results[ticker] = sentiment
        all_reasoning.append(f"--- {ticker} (score: {sentiment['score']}) ---\n{reasoning}")

    return results, "\n\n".join(all_reasoning)
