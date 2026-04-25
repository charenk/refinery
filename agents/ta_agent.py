"""
Technical Analysis agent: deep analysis of scanner candidates via Claude.

Uses call_with_cached_context() to separate memory (cached) from live data (fresh).
Model tier: analysis (Sonnet) for full TA calls.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import pandas as pd

from agents import memory_agent as mem
from utils import claude_client, data_fetcher, indicators
from utils.context_builder import build_ta_context
from ui import events

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a technical analyst monitoring US equities, ETFs, and Canadian stocks
on behalf of a personal investor on a multi-day to multi-week horizon. You have access to
accumulated knowledge about specific tickers and historical pattern performance.

Your response must contain exactly two sections:

ANALYSIS:
Entry zone, Target 1, Target 2, stop loss, R:R ratio, and a 3-4 sentence
plain-language summary. Be specific about what you are seeing and why it matters.

REASONING RECORD:
The explicit logic behind your recommendation. What memory context influenced
your decision. What risks you considered and why you weighted them as you did.
What would need to be true for this setup to fail. This record will be
compared against the actual outcome, so be honest and specific.

If your ticker knowledge contradicts the setup signal, say so explicitly.
If you have limited prior knowledge on this ticker, say so."""


def _format_live_data(ticker: str, df: pd.DataFrame, scanner_result: dict,
                      regime: str, vix: float | None) -> str:
    """Format today's live data for the TA agent call."""
    last = df.iloc[-1]
    levels = indicators.get_key_levels(df)
    ema_trend = indicators.get_ema_trend(df)

    parts = [
        f"## Live data for {ticker} as of {datetime.now().strftime('%Y-%m-%d')}",
        f"Close: ${last['close']:.2f} | Regime: {regime} | VIX: {vix or 'N/A'}",
        f"EMA alignment: {ema_trend}",
        f"Support: ${levels['support']} | Resistance: ${levels['resistance']} | Pivot: ${levels['pivot']}",
        "",
    ]

    # Key indicators
    indicator_lines = []
    for col, label in [
        ("rsi", "RSI"), ("atr", "ATR"), ("ADX_14", "ADX"),
        ("MACD_12_26_9", "MACD"), ("MACDh_12_26_9", "MACD Histogram"),
        ("STOCHk_14_3_3", "Stoch %K"), ("STOCHd_14_3_3", "Stoch %D"),
    ]:
        val = last.get(col)
        if pd.notna(val):
            indicator_lines.append(f"  {label}: {val:.2f}")
    if indicator_lines:
        parts.append("Indicators:")
        parts.extend(indicator_lines)
        parts.append("")

    # EMAs
    ema_lines = []
    for period in [9, 20, 50, 200]:
        val = last.get(f"ema_{period}")
        if pd.notna(val):
            ema_lines.append(f"  EMA {period}: ${val:.2f}")
    if ema_lines:
        parts.append("Moving averages:")
        parts.extend(ema_lines)
        parts.append("")

    # Volume
    vol = last.get("volume", 0)
    vol_sma = last.get("vol_sma_20", 0)
    if pd.notna(vol_sma) and vol_sma > 0:
        parts.append(f"Volume: {vol:,.0f} ({vol / vol_sma:.1f}x 20-day avg)")
    parts.append("")

    # Recent price action (last 5 days)
    parts.append("Recent 5-day price action:")
    for _, row in df.tail(5).iterrows():
        parts.append(
            f"  {row.name.strftime('%Y-%m-%d') if hasattr(row.name, 'strftime') else str(row.name)}: "
            f"O ${row['open']:.2f} H ${row['high']:.2f} L ${row['low']:.2f} C ${row['close']:.2f} "
            f"V {row['volume']:,.0f}"
        )
    parts.append("")

    # Scanner context
    parts.append(f"## Scanner assessment")
    parts.append(f"Setup type: {scanner_result.get('setup_type', 'unknown')}")
    parts.append(f"Quality score: {scanner_result.get('quality_score', 'N/A')}/5")
    parts.append(f"Scanner entry: ${scanner_result.get('entry_low', 'N/A')}-${scanner_result.get('entry_high', 'N/A')}")
    parts.append(f"Scanner T1: ${scanner_result.get('target_1', 'N/A')} | T2: ${scanner_result.get('target_2', 'N/A')}")
    parts.append(f"Scanner stop: ${scanner_result.get('stop', 'N/A')} | R:R: {scanner_result.get('rr_ratio', 'N/A')}")

    return "\n".join(parts)


def _parse_response(response_text: str) -> tuple[dict, str]:
    """Parse Claude's response into analysis dict and reasoning record."""
    analysis = {}
    reasoning_record = ""

    # Split on sections
    text = response_text.strip()

    if "ANALYSIS:" in text and "REASONING RECORD:" in text:
        analysis_section = text.split("REASONING RECORD:")[0]
        analysis_section = analysis_section.split("ANALYSIS:")[-1].strip()
        reasoning_record = text.split("REASONING RECORD:")[-1].strip()
    else:
        # Fallback: treat entire response as analysis
        analysis_section = text
        reasoning_record = text

    analysis["summary"] = analysis_section

    # Try to extract numeric values from analysis
    for line in analysis_section.split("\n"):
        line_lower = line.lower().strip()
        if "entry" in line_lower and "$" in line:
            analysis["entry_text"] = line.strip()
        if "target 1" in line_lower or "t1" in line_lower:
            analysis["target_1_text"] = line.strip()
        if "target 2" in line_lower or "t2" in line_lower:
            analysis["target_2_text"] = line.strip()
        if "stop" in line_lower and "$" in line:
            analysis["stop_text"] = line.strip()
        if "r:r" in line_lower or "risk" in line_lower and "reward" in line_lower:
            analysis["rr_text"] = line.strip()

    return analysis, reasoning_record


def analyze(
    ticker: str,
    category: str,
    scanner_result: dict,
    regime: str,
    vix: float | None = None,
) -> tuple[dict, str]:
    """
    Run deep TA analysis on a single ticker using Claude.

    Args:
        ticker: stock ticker symbol
        category: category from config.CANDIDATE_POOLS
        scanner_result: dict from scanner with setup_type, quality_score, levels
        regime: current market regime
        vix: current VIX level

    Returns:
        (signal_dict, reasoning_record)
        signal_dict: full signal ready for memory_agent.save_signal()
        reasoning_record: Claude's explicit reasoning
    """
    events.agent_state("ta", "active")
    events.log("ta", f"Analyzing {ticker} ({scanner_result.get('setup_type', '?')})")

    # Fetch fresh data
    df = data_fetcher.get_ohlcv(ticker)
    if df.empty:
        logger.warning("TA agent: %s dropped, no OHLCV data returned", ticker)
        events.log("ta", f"{ticker}: DROPPED (no data)")
        events.agent_state("ta", "error")
        return {}, f"No data available for {ticker}"

    df = indicators.compute_all(df)

    # Build context (cached memory + live data)
    cached_context = build_ta_context(ticker)
    live_data = _format_live_data(ticker, df, scanner_result, regime, vix)

    events.agent_state("ta", "reading")
    events.packet("mem", "ta", "#2DAE85")

    # Call Claude with cached context pattern
    try:
        response = claude_client.call_with_cached_context(
            system_prompt=SYSTEM_PROMPT,
            cached_context=cached_context,
            live_query=live_data,
            model="analysis",
            max_tokens=1200,
        )
    except Exception as e:
        logger.error("TA agent: %s dropped, Claude call failed: %s", ticker, e)
        events.log("ta", f"{ticker}: DROPPED (Claude API error)")
        events.agent_state("ta", "error")
        return {}, f"Claude API call failed for {ticker}: {e}"

    events.agent_state("ta", "writing")

    # Parse response
    analysis, reasoning_record = _parse_response(response)

    # Get FX rate for Canadian tickers
    cadusd = None
    try:
        fx = data_fetcher.get_fx_rates()
        cadusd = fx.get("CADUSD=X")
    except Exception:
        pass

    # Build signal dict using scanner levels as defaults
    signal = {
        "date": datetime.now().date().isoformat(),
        "ticker": ticker,
        "category": category,
        "setup_type": scanner_result.get("setup_type", "unknown"),
        "quality_score": scanner_result.get("quality_score", 3),
        "entry_low": scanner_result.get("entry_low", 0),
        "entry_high": scanner_result.get("entry_high", 0),
        "target_1": scanner_result.get("target_1", 0),
        "target_2": scanner_result.get("target_2", 0),
        "stop": scanner_result.get("stop", 0),
        "rr_ratio": scanner_result.get("rr_ratio", 0),
        "regime": regime,
        "vix_at_signal": vix,
        "cadusd_at_signal": cadusd,
        "reasoning": reasoning_record,
        "sentiment_score": None,
        "analysis_summary": analysis.get("summary", ""),
    }

    # Save reasoning record to ticker knowledge
    mem.save_reasoning_record("ta_agent", ticker, reasoning_record[:2000])

    events.packet("ta", "mem", "#E8A87C")
    events.agent_state("ta", "done")
    events.log("ta", f"{ticker}: analysis complete")

    return signal, reasoning_record


def analyze_batch(
    candidates: list[dict],
    regime: str,
    vix: float | None = None,
    max_signals: int = 8,
) -> tuple[list[dict], str]:
    """
    Analyze multiple scanner candidates sequentially.
    Stops after max_signals successful analyses.

    Returns:
        (signals, combined_reasoning)
    """
    from config import REPORT

    max_signals = min(max_signals, REPORT["max_watchlist_items"])
    signals = []
    all_reasoning = []

    for candidate in candidates:
        if len(signals) >= max_signals:
            break

        ticker = candidate["ticker"]
        category = candidate["category"]

        signal, reasoning = analyze(
            ticker=ticker,
            category=category,
            scanner_result=candidate,
            regime=regime,
            vix=vix,
        )

        if signal and signal.get("ticker"):
            signals.append(signal)
            all_reasoning.append(f"--- {ticker} ---\n{reasoning}")
        else:
            logger.warning("TA batch: %s produced no signal, skipping", ticker)
            all_reasoning.append(f"--- {ticker} ---\nDROPPED: {reasoning}")

    combined_reasoning = "\n\n".join(all_reasoning)
    return signals, combined_reasoning
