"""
Learning agent: weekly review of signals and outcomes to extract lessons.

Implements the learning ratchet: proposed changes trial for 15 days,
must show >5% win rate improvement to become permanent.
Model tier: analysis (Sonnet) via batch API for weekly reviews.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from agents import memory_agent as mem
from utils import claude_client
from ui import events

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are reviewing one week of trading signals and their outcomes to extract
actionable lessons that improve future signal quality.

For each insight you identify, specify:
1. What pattern you observed (with supporting statistics)
2. Which scanner/TA parameter it suggests changing
3. Whether it meets the ratchet threshold (>5% win rate impact expected)
4. Proposed change as: parameter, old value, new value, hypothesis

Do not propose changes without statistical backing.
Do not propose more than 3 changes per weekly review. Prioritize the highest-impact.
Flag any setup types or categories that should have elevated caution next week."""


def _get_weekly_signals() -> list[dict]:
    """Get all signals from the past 7 days."""
    with mem.get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM trades
               WHERE julianday('now') - julianday(date) <= 7
               ORDER BY date DESC""",
        ).fetchall()
        return [dict(r) for r in rows]


def _get_resolved_signals(days: int = 30) -> list[dict]:
    """Get resolved signals from recent period for statistics."""
    with mem.get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM trades
               WHERE outcome != 'pending'
               AND julianday('now') - julianday(date) <= ?
               ORDER BY date DESC""",
            (days,),
        ).fetchall()
        return [dict(r) for r in rows]


def _compute_stats(signals: list[dict]) -> dict:
    """Compute win rates and statistics from a set of resolved signals."""
    if not signals:
        return {"total": 0, "win_rate": 0.0}

    resolved = [s for s in signals if s["outcome"] != "pending"]
    if not resolved:
        return {"total": len(signals), "resolved": 0, "win_rate": 0.0}

    wins = sum(1 for s in resolved if s["outcome"] in ("hit_t1", "hit_t2"))
    total = len(resolved)

    # By setup type
    by_setup = {}
    for s in resolved:
        st = s.get("setup_type", "unknown")
        if st not in by_setup:
            by_setup[st] = {"wins": 0, "total": 0}
        by_setup[st]["total"] += 1
        if s["outcome"] in ("hit_t1", "hit_t2"):
            by_setup[st]["wins"] += 1

    # By category
    by_category = {}
    for s in resolved:
        cat = s.get("category", "unknown")
        if cat not in by_category:
            by_category[cat] = {"wins": 0, "total": 0}
        by_category[cat]["total"] += 1
        if s["outcome"] in ("hit_t1", "hit_t2"):
            by_category[cat]["wins"] += 1

    return {
        "total": len(signals),
        "resolved": total,
        "wins": wins,
        "win_rate": wins / total if total > 0 else 0.0,
        "by_setup": {k: {**v, "win_rate": v["wins"] / v["total"] if v["total"] > 0 else 0}
                     for k, v in by_setup.items()},
        "by_category": {k: {**v, "win_rate": v["wins"] / v["total"] if v["total"] > 0 else 0}
                        for k, v in by_category.items()},
    }


def _check_active_experiments() -> list[dict]:
    """Check and resolve any active strategy experiments."""
    from config import LEARNING

    with mem.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM strategy_experiments WHERE outcome='pending'"
        ).fetchall()
        experiments = [dict(r) for r in rows]

    resolved = []
    for exp in experiments:
        if not exp.get("trial_start"):
            continue

        trial_start = datetime.fromisoformat(exp["trial_start"])
        days_active = (datetime.now() - trial_start).days

        if days_active >= LEARNING["ratchet_trial_days"]:
            # Trial period is over, evaluate
            current_win_rate = mem.get_win_rate(last_n=20) or 0
            baseline = exp.get("baseline_winrate", 0) or 0
            improvement = current_win_rate - baseline

            if improvement >= LEARNING["ratchet_improvement_threshold"]:
                outcome = "committed"
                reason = f"Win rate improved by {improvement:.1%} (baseline {baseline:.1%} -> {current_win_rate:.1%})"
            else:
                outcome = "reverted"
                reason = f"Win rate improvement {improvement:.1%} below threshold {LEARNING['ratchet_improvement_threshold']:.0%}"

            with mem.get_conn() as conn:
                conn.execute(
                    """UPDATE strategy_experiments
                       SET outcome=?, trial_winrate=?, revert_reason=?, trial_end=?
                       WHERE id=?""",
                    (outcome, current_win_rate, reason,
                     datetime.now().date().isoformat(), exp["id"]),
                )

            resolved.append({**exp, "outcome": outcome, "reason": reason})

    return resolved


def _save_experiment(proposal: dict) -> int:
    """Save a new strategy experiment to the database."""
    baseline = mem.get_win_rate(last_n=20) or 0

    with mem.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO strategy_experiments
               (proposed_date, parameter, old_value, new_value, hypothesis,
                trial_start, baseline_winrate)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().date().isoformat(),
             proposal.get("parameter", ""),
             proposal.get("old_value", ""),
             proposal.get("new_value", ""),
             proposal.get("hypothesis", ""),
             datetime.now().date().isoformat(),
             baseline),
        )
        return cur.lastrowid


def weekly_review() -> tuple[dict, str]:
    """
    Run the weekly learning review.

    Analyzes recent signals, proposes parameter changes (subject to ratchet),
    and resolves any active experiments.

    Returns:
        (review_dict, reasoning_record)
    """
    events.agent_state("learn", "active")
    events.log("learn", "Starting weekly review")

    # Gather data
    weekly_signals = _get_weekly_signals()
    all_resolved = _get_resolved_signals(days=30)
    weekly_stats = _compute_stats(weekly_signals)
    overall_stats = _compute_stats(all_resolved)

    # Check active experiments
    resolved_experiments = _check_active_experiments()

    # Build prompt for Claude
    data_parts = [
        f"## Weekly review: {datetime.now().strftime('%Y-%m-%d')}",
        f"\n### This week's signals: {weekly_stats['total']}",
        f"Resolved: {weekly_stats.get('resolved', 0)} | Win rate: {weekly_stats['win_rate']:.0%}",
    ]

    if weekly_stats.get("by_setup"):
        data_parts.append("\nBy setup type:")
        for setup, stats in weekly_stats["by_setup"].items():
            data_parts.append(f"  {setup}: {stats['wins']}/{stats['total']} ({stats['win_rate']:.0%})")

    if weekly_stats.get("by_category"):
        data_parts.append("\nBy category:")
        for cat, stats in weekly_stats["by_category"].items():
            data_parts.append(f"  {cat}: {stats['wins']}/{stats['total']} ({stats['win_rate']:.0%})")

    data_parts.append(f"\n### 30-day statistics")
    data_parts.append(f"Total resolved: {overall_stats.get('resolved', 0)} | Win rate: {overall_stats['win_rate']:.0%}")

    if resolved_experiments:
        data_parts.append("\n### Experiment results:")
        for exp in resolved_experiments:
            data_parts.append(f"  {exp['parameter']}: {exp['outcome']} - {exp.get('reason', '')}")

    # Include recent post-mortems
    data_parts.append("\n### Recent post-mortem lessons:")
    for signal in all_resolved[:10]:
        if signal.get("post_mortem"):
            data_parts.append(f"  {signal['ticker']} ({signal['outcome']}): {signal['post_mortem'][:200]}")

    user_message = "\n".join(data_parts)

    try:
        response = claude_client.call(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_message,
            model="analysis",
            max_tokens=2000,
        )
    except Exception as e:
        logger.error(f"Learning agent Claude call failed: {e}")
        events.agent_state("learn", "error")
        return {"error": str(e)}, str(e)

    review = {
        "date": datetime.now().date().isoformat(),
        "weekly_stats": weekly_stats,
        "overall_stats": overall_stats,
        "resolved_experiments": resolved_experiments,
        "claude_analysis": response,
    }

    # Append to strategy notes
    try:
        from config import MEMORY
        with open(MEMORY["strategy_notes"], "a") as f:
            f.write(f"\n\n## Weekly Review - {datetime.now().date().isoformat()}\n")
            f.write(f"Win rate: {weekly_stats['win_rate']:.0%} ({weekly_stats.get('resolved', 0)} resolved)\n")
            f.write(response[:1000])
    except Exception as e:
        logger.error(f"Failed to update strategy notes: {e}")

    mem.save_reasoning_record("learning_agent", "WEEKLY", response[:2000])

    events.agent_state("learn", "done")
    events.log("learn", f"Weekly review complete. Win rate: {weekly_stats['win_rate']:.0%}")

    return review, response
