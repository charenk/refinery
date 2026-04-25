"""
Post-mortem agent: analyzes resolved signals to extract lessons.

Reviews signals that have hit targets, stops, or expired.
Model tier: analysis (Sonnet) for honest, specific post-mortems.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from agents import memory_agent as mem
from utils import claude_client, data_fetcher, indicators
from utils.context_builder import build_postmortem_context
from ui import events

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are analyzing a trading signal that has now resolved. Your job is to
produce an honest, specific post-mortem that improves future analysis.

Structure your response as:

WHAT I GOT RIGHT: (specific signals that correctly predicted the move)
WHAT I MISSED: (what was visible in hindsight but underweighted)
ERROR PATTERN: (is this a one-off or a recurring mistake?)
LESSON: (one concrete, specific thing to look for differently next time)
PATTERN UPDATE NEEDED: yes/no, and if yes, what specifically should change
  in the pattern knowledge for this setup type in this regime?

Be direct. Vague post-mortems are useless. Name the specific indicator,
the specific condition, the specific mistake."""


def _determine_outcome(trade: dict) -> tuple[str, float, float]:
    """
    Check if a pending signal has resolved by comparing current price to targets/stop.

    Returns:
        (outcome, exit_price, pnl_pct)
        outcome: 'hit_t1', 'hit_t2', 'stopped', 'expired', or 'pending'
    """
    ticker = trade["ticker"]
    df = data_fetcher.get_ohlcv(ticker, days=10)
    if df.empty:
        return "pending", 0.0, 0.0

    # Get the highest high and lowest low since signal date
    signal_date = trade["date"]
    try:
        # Filter to rows after signal date
        df.index = pd.to_datetime(df.index)
        mask = df.index >= pd.Timestamp(signal_date)
        recent = df[mask] if mask.any() else df.tail(5)
    except Exception:
        recent = df.tail(5)

    if recent.empty:
        return "pending", 0.0, 0.0

    high_since = float(recent["high"].max())
    low_since = float(recent["low"].min())
    current = float(recent.iloc[-1]["close"])
    entry_mid = (trade["entry_low"] + trade["entry_high"]) / 2

    # Check stop first (worst case)
    if trade["stop"] > 0 and low_since <= trade["stop"]:
        pnl = (trade["stop"] - entry_mid) / entry_mid * 100
        return "stopped", trade["stop"], round(pnl, 2)

    # Check T2 (best case)
    if trade.get("target_2") and trade["target_2"] > 0 and high_since >= trade["target_2"]:
        pnl = (trade["target_2"] - entry_mid) / entry_mid * 100
        return "hit_t2", trade["target_2"], round(pnl, 2)

    # Check T1
    if trade["target_1"] > 0 and high_since >= trade["target_1"]:
        pnl = (trade["target_1"] - entry_mid) / entry_mid * 100
        return "hit_t1", trade["target_1"], round(pnl, 2)

    return "pending", current, round((current - entry_mid) / entry_mid * 100, 2) if entry_mid > 0 else 0.0


def analyze_single(trade_id: int) -> tuple[dict, str]:
    """
    Run post-mortem analysis on a single resolved trade.

    Returns:
        (postmortem_dict, reasoning_record)
    """
    events.agent_state("post", "active")

    # Build context from memory
    context = build_postmortem_context(trade_id)
    if not context:
        events.agent_state("post", "error")
        return {}, f"Trade {trade_id} not found"

    # Fetch current chart for hindsight analysis
    with mem.get_conn() as conn:
        trade = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not trade:
        return {}, f"Trade {trade_id} not found"
    trade = dict(trade)

    df = data_fetcher.get_ohlcv(trade["ticker"], days=30)
    live_parts = [context]
    if not df.empty:
        df = indicators.compute_all(df)
        last = df.iloc[-1]
        live_parts.append(f"\n## Current chart state")
        live_parts.append(f"Close: ${last['close']:.2f}")
        rsi = last.get("rsi")
        if pd.notna(rsi):
            live_parts.append(f"RSI: {rsi:.1f}")
        ema_trend = indicators.get_ema_trend(df)
        live_parts.append(f"EMA trend: {ema_trend}")

    live_query = "\n".join(live_parts)

    events.packet("mem", "post", "#E76F51")

    try:
        response = claude_client.call(
            system_prompt=SYSTEM_PROMPT,
            user_message=live_query,
            model="analysis",
            max_tokens=1500,
        )
    except Exception as e:
        logger.error(f"Post-mortem Claude call failed for trade {trade_id}: {e}")
        events.agent_state("post", "error")
        return {}, str(e)

    # Parse sections
    postmortem = {
        "trade_id": trade_id,
        "ticker": trade["ticker"],
        "full_text": response,
    }

    for section in ["WHAT I GOT RIGHT:", "WHAT I MISSED:", "ERROR PATTERN:", "LESSON:", "PATTERN UPDATE NEEDED:"]:
        key = section.replace(":", "").lower().replace(" ", "_")
        if section in response:
            # Get text between this section and the next
            after = response.split(section, 1)[1]
            # Find next section header
            next_section = None
            for s in ["WHAT I GOT RIGHT:", "WHAT I MISSED:", "ERROR PATTERN:", "LESSON:", "PATTERN UPDATE NEEDED:"]:
                if s != section and s in after:
                    idx = after.index(s)
                    if next_section is None or idx < next_section[1]:
                        next_section = (s, idx)
            if next_section:
                postmortem[key] = after[:next_section[1]].strip()
            else:
                postmortem[key] = after.strip()

    # Update trade outcome with post-mortem text
    mem.update_outcome(
        trade_id=trade_id,
        outcome=trade.get("outcome", "reviewed"),
        exit_price=trade.get("exit_price", 0),
        pnl_pct=trade.get("pnl_pct", 0),
        post_mortem=response[:2000],
    )

    mem.save_reasoning_record("postmortem_agent", trade["ticker"], response[:2000])

    events.packet("post", "mem", "#E8A87C")
    events.agent_state("post", "done")

    return postmortem, response


def check_and_resolve_pending(expiry_days: int = 5) -> tuple[list[dict], str]:
    """
    Check all pending signals, resolve those that have hit targets/stops/expired,
    then run post-mortems on resolved signals.

    Returns:
        (resolved_trades, combined_reasoning)
    """
    from config import MEMORY

    expiry_days = MEMORY.get("postmortem_expiry_days", expiry_days)
    pending = mem.get_pending_signals(expiry_days=expiry_days + 5)

    if not pending:
        return [], "No pending signals to check."

    resolved = []
    all_reasoning = [f"Post-mortem check at {datetime.now().isoformat()}", ""]

    for trade in pending:
        outcome, exit_price, pnl_pct = _determine_outcome(trade)

        if outcome == "pending":
            # Check if expired
            from datetime import datetime as dt
            days_old = (dt.now() - dt.fromisoformat(trade["date"])).days
            if days_old > expiry_days:
                outcome = "expired"
            else:
                continue

        # Update outcome in DB
        mem.update_outcome(trade["id"], outcome, exit_price, pnl_pct, "")
        all_reasoning.append(f"{trade['ticker']}: {outcome} at ${exit_price:.2f} ({pnl_pct:+.1f}%)")

        # Run post-mortem
        postmortem, reasoning = analyze_single(trade["id"])
        if postmortem:
            resolved.append({**postmortem, "outcome": outcome, "pnl_pct": pnl_pct})
            all_reasoning.append(f"  Post-mortem: {reasoning[:300]}")

    combined = "\n".join(all_reasoning)
    events.log("post", f"Resolved {len(resolved)} signals")
    return resolved, combined
