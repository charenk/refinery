"""
Roster agent: manages ticker tiers across categories.

Evaluates ticker health scores to propose promotions (watch -> active),
demotions (active -> watch), and evictions.
No Claude API calls. Pure rule-based logic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from agents import memory_agent as mem
from utils import data_fetcher, indicators
from ui import events

logger = logging.getLogger(__name__)


def _load_roster() -> dict:
    """Load roster from file, or initialize from config defaults."""
    from config import MEMORY, CANDIDATE_POOLS, ROSTER

    try:
        with open(MEMORY["roster_file"]) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Initialize from config
        roster = {"last_updated": datetime.now().date().isoformat(), "categories": {}, "pending_changes": []}
        active_per_cat = ROSTER["active_tier_per_category"]
        for category, tickers in CANDIDATE_POOLS.items():
            roster["categories"][category] = {
                "active": tickers[:active_per_cat],
                "watch": tickers[active_per_cat:],
                "pinned": [],
            }
        return roster


def _save_roster(roster: dict) -> None:
    """Save roster to file."""
    from config import MEMORY
    roster["last_updated"] = datetime.now().date().isoformat()
    with open(MEMORY["roster_file"], "w") as f:
        json.dump(roster, f, indent=2)


def _ticker_health(ticker: str) -> float:
    """
    Compute a health score (0.0-1.0) for a ticker based on:
    - Recent signal win rate
    - Volume trend
    - Price trend alignment
    """
    score = 0.5  # baseline

    # Win rate component
    win_rate = mem.get_win_rate(last_n=10)
    if win_rate is not None:
        # Get ticker-specific signals
        recent = mem.get_recent_signals(ticker=ticker, limit=5)
        if recent:
            resolved = [s for s in recent if s["outcome"] != "pending"]
            if resolved:
                wins = sum(1 for s in resolved if s["outcome"] in ("hit_t1", "hit_t2"))
                ticker_wr = wins / len(resolved)
                score += (ticker_wr - 0.5) * 0.4  # +/- 0.2

    # Technical health
    try:
        df = data_fetcher.get_ohlcv(ticker, days=30)
        if not df.empty:
            df = indicators.compute_all(df)
            ema_trend = indicators.get_ema_trend(df)
            if ema_trend == "above_all":
                score += 0.15
            elif ema_trend == "below_all":
                score -= 0.15

            # Volume trend
            last = df.iloc[-1]
            vol = last.get("volume", 0)
            vol_sma = last.get("vol_sma_20", 0)
            import pandas as pd
            if pd.notna(vol_sma) and vol_sma > 0:
                vol_ratio = vol / vol_sma
                if vol_ratio > 1.5:
                    score += 0.1
                elif vol_ratio < 0.5:
                    score -= 0.1
    except Exception:
        pass

    return max(0.0, min(1.0, score))


def evaluate() -> tuple[list[dict], str]:
    """
    Evaluate all roster positions and propose changes.

    Returns:
        (proposals, reasoning_record)
        proposals: list of {category, ticker, action, reason, health_score}
        action: 'promote', 'demote', 'evict'
    """
    from config import ROSTER as ROSTER_CFG

    events.agent_state("roster", "active")
    events.log("roster", "Evaluating roster health")

    roster = _load_roster()
    proposals = []
    reasoning_lines = [f"Roster evaluation at {datetime.now().isoformat()}", ""]

    for category, data in roster["categories"].items():
        active = data.get("active", [])
        watch = data.get("watch", [])
        pinned = data.get("pinned", [])

        reasoning_lines.append(f"## {category}")
        reasoning_lines.append(f"Active: {active} | Watch: {watch}")

        # Score active tickers
        active_scores = {}
        for ticker in active:
            health = _ticker_health(ticker)
            active_scores[ticker] = health
            reasoning_lines.append(f"  {ticker} (active): health {health:.2f}")

            # Check for demotion (unless pinned)
            if ticker not in pinned and health < ROSTER_CFG["eviction_health_threshold"]:
                proposals.append({
                    "category": category,
                    "ticker": ticker,
                    "action": "demote",
                    "reason": f"Health {health:.2f} below threshold {ROSTER_CFG['eviction_health_threshold']}",
                    "health_score": health,
                })

        # Score watch tickers
        watch_scores = {}
        for ticker in watch:
            health = _ticker_health(ticker)
            watch_scores[ticker] = health
            reasoning_lines.append(f"  {ticker} (watch): health {health:.2f}")

            # Check for promotion: watch ticker outperforms weakest active
            if active_scores:
                weakest_active = min(active_scores.values())
                if health > weakest_active + 0.15:
                    weakest_ticker = min(active_scores, key=active_scores.get)
                    if weakest_ticker not in pinned:
                        proposals.append({
                            "category": category,
                            "ticker": ticker,
                            "action": "promote",
                            "reason": f"Health {health:.2f} exceeds weakest active ({weakest_ticker}: {weakest_active:.2f})",
                            "health_score": health,
                        })

        reasoning_lines.append("")

    # Save proposals as pending changes
    if proposals:
        roster["pending_changes"] = [
            {**p, "proposed_date": datetime.now().date().isoformat()}
            for p in proposals
        ]
        _save_roster(roster)

    reasoning_record = "\n".join(reasoning_lines)
    mem.save_reasoning_record("roster_agent", "ROSTER", reasoning_record[:2000])

    events.agent_state("roster", "done")
    events.log("roster", f"Evaluation complete: {len(proposals)} proposals")

    return proposals, reasoning_record


def apply_change(category: str, ticker: str, action: str) -> bool:
    """
    Apply an approved roster change.

    Args:
        category: category name
        ticker: ticker symbol
        action: 'promote', 'demote', 'evict', 'add', 'pin', 'unpin'

    Returns:
        True if change was applied
    """
    roster = _load_roster()
    cat_data = roster["categories"].get(category)
    if not cat_data:
        logger.error(f"Category {category} not found in roster")
        return False

    active = cat_data.get("active", [])
    watch = cat_data.get("watch", [])
    pinned = cat_data.get("pinned", [])

    if action == "promote" and ticker in watch:
        watch.remove(ticker)
        active.append(ticker)
    elif action == "demote" and ticker in active:
        active.remove(ticker)
        watch.append(ticker)
    elif action == "evict":
        if ticker in active:
            active.remove(ticker)
        if ticker in watch:
            watch.remove(ticker)
        if ticker in pinned:
            pinned.remove(ticker)
    elif action == "add":
        if ticker not in active and ticker not in watch:
            watch.append(ticker)
    elif action == "pin":
        if ticker not in pinned:
            pinned.append(ticker)
    elif action == "unpin":
        if ticker in pinned:
            pinned.remove(ticker)
    else:
        return False

    cat_data["active"] = active
    cat_data["watch"] = watch
    cat_data["pinned"] = pinned

    # Clear this from pending changes
    roster["pending_changes"] = [
        p for p in roster.get("pending_changes", [])
        if not (p["category"] == category and p["ticker"] == ticker)
    ]

    _save_roster(roster)
    return True
