"""
Portfolio agent: monitors current holdings for risk and opportunity.

Checks holdings against stop levels, target proximity, and overnight risk.
Model tier: lightweight (Haiku) for routine checks, analysis (Sonnet) for alerts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import pandas as pd

from agents import memory_agent as mem
from utils import claude_client, data_fetcher, indicators
from utils.context_builder import build_portfolio_context
from ui import events

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a portfolio risk analyst monitoring a personal investment account.

Review the current holdings and market data to assess:
1. Which positions are approaching their targets or stops
2. Any overnight risk that needs attention
3. Position-level and portfolio-level concerns

Your response must contain exactly two sections:

PORTFOLIO ASSESSMENT:
For each holding, provide: status (on_track/caution/alert), distance to T1, distance to stop,
and a one-line note. Then provide a portfolio-level summary.

REASONING RECORD:
Why you assessed each position as you did. What risks you are most concerned about.
What regime or macro factors influence your view. What actions you would recommend."""


def _load_portfolio() -> dict:
    """Load and validate the portfolio. Invalid entries are dropped with a warning."""
    from config import MEMORY
    from utils.portfolio_loader import load_portfolio
    return load_portfolio(MEMORY["portfolio_file"])


def check_holdings(
    regime: str,
    vix: float | None = None,
) -> tuple[list[dict], str]:
    """
    Check all holdings for alerts and risk.

    Returns:
        (alerts, reasoning_record)
        alerts: list of {ticker, alert_type, message, severity}
        reasoning_record: assessment summary
    """
    from config import ALERTS

    events.agent_state("port", "active")

    portfolio = _load_portfolio()
    holdings = portfolio.get("holdings", [])

    if not holdings:
        events.agent_state("port", "done")
        return [], "No holdings to check."

    alerts = []
    assessment_lines = [f"Portfolio check at {datetime.now().isoformat()}", f"Regime: {regime} | VIX: {vix}", ""]

    for holding in holdings:
        ticker = holding["ticker"]
        try:
            df = data_fetcher.get_ohlcv(ticker, days=30)
            if df.empty:
                assessment_lines.append(f"{ticker}: no data available")
                continue

            df = indicators.compute_all(df)
            last = df.iloc[-1]
            close = float(last["close"])

            target_1 = holding.get("target_1_cad", 0)
            stop = holding.get("stop_cad", 0)
            avg_cost = holding.get("avg_cost_cad", 0)

            # P&L
            pnl_pct = ((close - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

            assessment_lines.append(f"{ticker}: ${close:.2f} (P&L: {pnl_pct:+.1f}%)")

            # Check target proximity
            if target_1 > 0:
                t1_distance = (target_1 - close) / close
                if 0 < t1_distance <= ALERTS["target1_proximity_pct"]:
                    alerts.append({
                        "ticker": ticker,
                        "alert_type": "near_target",
                        "message": f"{ticker} within {t1_distance:.1%} of T1 (${target_1})",
                        "severity": "info",
                    })
                    assessment_lines.append(f"  NEAR TARGET: {t1_distance:.1%} from T1")

            # Check stop proximity
            if stop > 0:
                stop_distance = (close - stop) / close
                if 0 < stop_distance <= ALERTS["stop_proximity_pct"]:
                    alerts.append({
                        "ticker": ticker,
                        "alert_type": "near_stop",
                        "message": f"{ticker} within {stop_distance:.1%} of stop (${stop})",
                        "severity": "warning",
                    })
                    assessment_lines.append(f"  NEAR STOP: {stop_distance:.1%} from stop")
                elif stop_distance <= 0:
                    alerts.append({
                        "ticker": ticker,
                        "alert_type": "stop_breached",
                        "message": f"{ticker} BELOW stop (${stop}), currently ${close:.2f}",
                        "severity": "critical",
                    })
                    assessment_lines.append(f"  STOP BREACHED: below ${stop}")

            # Overnight move check
            if len(df) >= 2:
                prev_close = float(df.iloc[-2]["close"])
                overnight_pct = abs(close - prev_close) / prev_close
                if overnight_pct >= ALERTS["overnight_move_pct"]:
                    direction = "up" if close > prev_close else "down"
                    alerts.append({
                        "ticker": ticker,
                        "alert_type": "overnight_move",
                        "message": f"{ticker} moved {overnight_pct:.1%} {direction} (${prev_close:.2f} -> ${close:.2f})",
                        "severity": "warning",
                    })
                    assessment_lines.append(f"  OVERNIGHT MOVE: {overnight_pct:.1%} {direction}")

        except Exception as e:
            logger.error(f"Portfolio check failed for {ticker}: {e}")
            assessment_lines.append(f"  ERROR: {e}")

    reasoning_record = "\n".join(assessment_lines)

    # Save reasoning
    mem.save_reasoning_record("portfolio_agent", "PORTFOLIO", reasoning_record[:2000])

    events.agent_state("port", "done")
    events.log("port", f"Checked {len(holdings)} holdings, {len(alerts)} alerts")

    return alerts, reasoning_record


def deep_analysis(
    regime: str,
    vix: float | None = None,
) -> tuple[dict, str]:
    """
    Run Claude-powered deep portfolio analysis (used in daily brief).

    Returns:
        (analysis_dict, reasoning_record)
    """
    events.agent_state("port", "active")

    cached_context = build_portfolio_context()
    portfolio = _load_portfolio()
    holdings = portfolio.get("holdings", [])

    if not holdings:
        events.agent_state("port", "done")
        return {"summary": "No holdings"}, "Empty portfolio, no analysis needed."

    # Build live data for all holdings
    live_parts = [f"## Market data as of {datetime.now().strftime('%Y-%m-%d')}"]
    live_parts.append(f"Regime: {regime} | VIX: {vix or 'N/A'}\n")

    for holding in holdings:
        ticker = holding["ticker"]
        try:
            df = data_fetcher.get_ohlcv(ticker, days=30)
            if df.empty:
                continue
            df = indicators.compute_all(df)
            last = df.iloc[-1]
            live_parts.append(f"### {ticker}")
            live_parts.append(f"Close: ${last['close']:.2f}")

            rsi = last.get("rsi")
            if pd.notna(rsi):
                live_parts.append(f"RSI: {rsi:.1f}")

            ema_trend = indicators.get_ema_trend(df)
            live_parts.append(f"EMA trend: {ema_trend}")
            live_parts.append("")
        except Exception:
            continue

    live_query = "\n".join(live_parts)

    try:
        response = claude_client.call_with_cached_context(
            system_prompt=SYSTEM_PROMPT,
            cached_context=cached_context,
            live_query=live_query,
            model="analysis",
            max_tokens=2000,
        )
    except Exception as e:
        logger.error(f"Portfolio deep analysis failed: {e}")
        events.agent_state("port", "error")
        return {"summary": f"API error: {e}"}, str(e)

    # Parse response
    analysis = {"summary": response}
    reasoning_record = ""

    if "PORTFOLIO ASSESSMENT:" in response and "REASONING RECORD:" in response:
        analysis["summary"] = response.split("REASONING RECORD:")[0].split("PORTFOLIO ASSESSMENT:")[-1].strip()
        reasoning_record = response.split("REASONING RECORD:")[-1].strip()
    else:
        reasoning_record = response

    mem.save_reasoning_record("portfolio_agent", "PORTFOLIO", reasoning_record[:2000])

    events.agent_state("port", "done")
    return analysis, reasoning_record
