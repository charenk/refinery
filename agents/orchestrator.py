"""
Orchestrator: coordinates agent execution for each run type.

Each run script calls the appropriate orchestrator function,
which handles agent sequencing, data flow, and error recovery.
"""

from __future__ import annotations

import logging
from datetime import datetime

from agents import memory_agent as mem
from agents import scanner, ta_agent, sentiment_agent, portfolio_agent
from agents import postmortem_agent, learning_agent, roster_agent
from utils import data_fetcher, indicators
from ui import events

logger = logging.getLogger(__name__)

# Regime cache: avoids redundant SPY fetches + classify_regime calls
# when multiple run scripts execute within a short window.
_regime_cache: dict = {"data": None, "timestamp": None, "vix": None}
_REGIME_CACHE_TTL_HOURS = 4
_VIX_REFRESH_THRESHOLD = 0.15  # force refresh if VIX moves >15%


def _get_market_context() -> dict:
    """Fetch shared market context: regime, VIX, indices, FX.

    Results are cached for up to 4 hours. Cache is invalidated early
    if VIX moves more than 15% from the cached value.
    """
    now = datetime.now()

    # Check cache validity
    if _regime_cache["data"] is not None and _regime_cache["timestamp"] is not None:
        age_hours = (now - _regime_cache["timestamp"]).total_seconds() / 3600
        if age_hours < _REGIME_CACHE_TTL_HOURS:
            # Quick VIX check to see if conditions changed materially
            try:
                fresh_indices = data_fetcher.get_global_indices()
                fresh_vix = fresh_indices.get("^VIX")
                cached_vix = _regime_cache["vix"]
                if (
                    fresh_vix is not None
                    and cached_vix is not None
                    and cached_vix > 0
                    and abs(fresh_vix - cached_vix) / cached_vix
                    < _VIX_REFRESH_THRESHOLD
                ):
                    logger.debug("Returning cached market context (%.1fh old)", age_hours)
                    cached = dict(_regime_cache["data"])
                    cached["timestamp"] = now.isoformat()
                    return cached
                else:
                    logger.info("VIX moved significantly, refreshing regime cache")
            except Exception:
                # If VIX check fails, use cache anyway
                logger.debug("VIX check failed, returning cached context")
                cached = dict(_regime_cache["data"])
                cached["timestamp"] = now.isoformat()
                return cached

    # Full fetch
    spy_df = data_fetcher.get_ohlcv("SPY")
    regime = "range"
    vix = None

    if not spy_df.empty:
        spy_df = indicators.compute_all(spy_df)
        try:
            indices = data_fetcher.get_global_indices()
            vix = indices.get("^VIX")
        except Exception:
            pass
        regime = indicators.classify_regime(spy_df, vix=vix)

    # Get FX
    cadusd = None
    try:
        fx = data_fetcher.get_fx_rates()
        cadusd = fx.get("CADUSD=X")
    except Exception:
        pass

    result = {
        "regime": regime,
        "vix": vix,
        "cadusd": cadusd,
        "timestamp": now.isoformat(),
    }

    # Update cache
    _regime_cache["data"] = {"regime": regime, "vix": vix, "cadusd": cadusd}
    _regime_cache["timestamp"] = now
    _regime_cache["vix"] = vix

    return result


def run_overnight() -> dict:
    """
    6:30 AM EST: Lightweight pre-market check.
    - Active tier + portfolio scan
    - Uses Haiku
    - Always sends email
    """
    events.agent_state("orch", "active")
    events.log("orch", "Starting overnight run")

    mem.init_db()
    ctx = _get_market_context()

    # Scan active tier only
    active_candidates, _, scan_reasoning = scanner.scan_all(
        regime=ctx["regime"], vix=ctx["vix"], active_only=True
    )

    # Portfolio check
    alerts, port_reasoning = portfolio_agent.check_holdings(
        regime=ctx["regime"], vix=ctx["vix"]
    )

    # Check pending signals
    resolved, pm_reasoning = postmortem_agent.check_and_resolve_pending()

    result = {
        "type": "overnight",
        "timestamp": ctx["timestamp"],
        "regime": ctx["regime"],
        "vix": ctx["vix"],
        "candidates": active_candidates,
        "portfolio_alerts": alerts,
        "resolved_signals": resolved,
        "reasoning": {
            "scanner": scan_reasoning,
            "portfolio": port_reasoning,
            "postmortem": pm_reasoning,
        },
    }

    events.agent_state("orch", "done")
    return result


def run_daily(dry_run: bool = False, ticker: str | None = None) -> dict:
    """
    8:15 AM EST: Primary brief generation.
    - Full scan + TA analysis + sentiment
    - Uses Sonnet
    - Always sends HTML email
    """
    events.agent_state("orch", "active")
    events.log("orch", "Starting daily brief")

    mem.init_db()
    ctx = _get_market_context()

    # Kickoff: orchestrator dispatches the scanner.
    events.runner("orch", "scan", "#8B7FDD")

    # Full scan
    if ticker:
        # Single ticker mode for testing
        from config import CANDIDATE_POOLS
        category = None
        for cat, tickers in CANDIDATE_POOLS.items():
            if ticker in tickers:
                category = cat
                break
        if not category:
            category = "manual"

        candidates, scan_reasoning = scanner.scan_active_tier(
            category, [ticker], ctx["regime"], ctx["vix"]
        )
        watch_triggered = []
    else:
        candidates, watch_triggered, scan_reasoning = scanner.scan_all(
            regime=ctx["regime"], vix=ctx["vix"]
        )

    # Scanner hands its candidates to the TA agent.
    events.runner("scan", "ta", "#2DAE85")

    # TA analysis on top candidates
    signals, ta_reasoning = ta_agent.analyze_batch(
        candidates=candidates,
        regime=ctx["regime"],
        vix=ctx["vix"],
    )

    # TA pulls historical ticker knowledge from the memory store.
    events.runner("ta", "memory_db", "#4A8ADD")

    # Sentiment for signal tickers
    signal_tickers = [s["ticker"] for s in signals]
    sentiment_results, sent_reasoning = sentiment_agent.analyze_batch(
        tickers=signal_tickers,
        regime=ctx["regime"],
    )

    # Sentiment hands its scores back to the TA workflow.
    events.runner("senti", "ta", "#D86A40")

    # Attach sentiment scores to signals
    for signal in signals:
        sent = sentiment_results.get(signal["ticker"], {})
        signal["sentiment_score"] = sent.get("score", 0)

    # Save signals to DB (unless dry run)
    if not dry_run:
        for signal in signals:
            try:
                trade_id = mem.save_signal(signal)
                signal["trade_id"] = trade_id
            except Exception as e:
                logger.error(f"Failed to save signal for {signal['ticker']}: {e}")

    # Orchestrator delegates the portfolio check.
    events.runner("orch", "port", "#8B7FDD")

    # Portfolio check
    port_analysis, port_reasoning = portfolio_agent.deep_analysis(
        regime=ctx["regime"], vix=ctx["vix"]
    )

    # Brief record
    if not dry_run:
        try:
            mem.save_brief_record(
                date=datetime.now().date().isoformat(),
                regime=ctx["regime"],
                n_setups=len(signals),
                vix=ctx["vix"] or 0,
                cadusd=ctx["cadusd"] or 0,
                sp_futures_pct=0,
            )
        except Exception as e:
            logger.error(f"Failed to save brief record: {e}")

    result = {
        "type": "daily",
        "dry_run": dry_run,
        "timestamp": ctx["timestamp"],
        "regime": ctx["regime"],
        "vix": ctx["vix"],
        "cadusd": ctx["cadusd"],
        "signals": signals,
        "sentiment": sentiment_results,
        "portfolio": port_analysis,
        "watch_triggered": watch_triggered,
        "reasoning": {
            "scanner": scan_reasoning,
            "ta": ta_reasoning,
            "sentiment": sent_reasoning,
            "portfolio": port_reasoning,
        },
    }

    events.agent_state("orch", "done")
    events.log("orch", f"Daily brief complete: {len(signals)} signals")
    return result


def run_open_watch() -> dict:
    """
    9:45 AM EST: Post-open watch tier check.
    - All 100 tickers, watch tier triggers only
    - Uses Haiku
    - Alert only if triggered
    """
    events.agent_state("orch", "active")
    mem.init_db()
    ctx = _get_market_context()

    _, watch_triggered, scan_reasoning = scanner.scan_all(
        regime=ctx["regime"], vix=ctx["vix"]
    )

    result = {
        "type": "open_watch",
        "timestamp": ctx["timestamp"],
        "regime": ctx["regime"],
        "watch_triggered": watch_triggered,
        "reasoning": scan_reasoning,
    }

    events.agent_state("orch", "done")
    return result


def run_pulse() -> dict:
    """
    Every 30 min during market hours: watch tier quick check.
    - Watch tier only
    - Haiku, escalates to Sonnet if triggered
    """
    events.agent_state("orch", "active")
    mem.init_db()
    ctx = _get_market_context()

    _, watch_triggered, scan_reasoning = scanner.scan_all(
        regime=ctx["regime"], vix=ctx["vix"]
    )

    # If triggers found, run quick TA on triggered tickers
    escalated_signals = []
    if watch_triggered:
        for trigger in watch_triggered[:3]:  # max 3 escalations per pulse
            candidate = {
                "ticker": trigger["ticker"],
                "category": trigger["category"],
                "setup_type": "momentum",  # default for triggered watch tickers
                "quality_score": 3,
                "entry_low": trigger["close"] * 0.997,
                "entry_high": trigger["close"] * 1.003,
                "target_1": trigger["close"] * 1.03,
                "target_2": trigger["close"] * 1.05,
                "stop": trigger["close"] * 0.97,
                "rr_ratio": 1.0,
            }
            signal, reasoning = ta_agent.analyze(
                ticker=trigger["ticker"],
                category=trigger["category"],
                scanner_result=candidate,
                regime=ctx["regime"],
                vix=ctx["vix"],
            )
            if signal:
                escalated_signals.append(signal)

    # Portfolio quick check
    alerts, port_reasoning = portfolio_agent.check_holdings(
        regime=ctx["regime"], vix=ctx["vix"]
    )

    result = {
        "type": "pulse",
        "timestamp": ctx["timestamp"],
        "regime": ctx["regime"],
        "watch_triggered": watch_triggered,
        "escalated_signals": escalated_signals,
        "portfolio_alerts": alerts,
        "reasoning": {
            "scanner": scan_reasoning,
            "portfolio": port_reasoning,
        },
    }

    events.agent_state("orch", "done")
    return result


def run_midday() -> dict:
    """
    12:30 PM EST: Portfolio-only midday check.
    - Portfolio holdings only
    - Haiku
    - Alert only if triggered
    """
    events.agent_state("orch", "active")
    mem.init_db()
    ctx = _get_market_context()

    alerts, port_reasoning = portfolio_agent.check_holdings(
        regime=ctx["regime"], vix=ctx["vix"]
    )

    result = {
        "type": "midday",
        "timestamp": ctx["timestamp"],
        "regime": ctx["regime"],
        "portfolio_alerts": alerts,
        "reasoning": port_reasoning,
    }

    events.agent_state("orch", "done")
    return result


def run_eod() -> dict:
    """
    4:35 PM EST: End of day review.
    - Active tier + portfolio outcome analysis
    - Uses Sonnet Batch API
    - Always sends EOD summary
    """
    events.agent_state("orch", "active")
    events.log("orch", "Starting EOD run")

    mem.init_db()
    ctx = _get_market_context()

    # Resolve pending signals
    resolved, pm_reasoning = postmortem_agent.check_and_resolve_pending()

    # Portfolio check
    alerts, port_reasoning = portfolio_agent.check_holdings(
        regime=ctx["regime"], vix=ctx["vix"]
    )

    result = {
        "type": "eod",
        "timestamp": ctx["timestamp"],
        "regime": ctx["regime"],
        "vix": ctx["vix"],
        "resolved_signals": resolved,
        "portfolio_alerts": alerts,
        "n_tracked": len(mem.get_pending_signals()),
        "overnight_risk": any(a["severity"] == "critical" for a in alerts),
        "reasoning": {
            "postmortem": pm_reasoning,
            "portfolio": port_reasoning,
        },
    }

    events.agent_state("orch", "done")
    events.log("orch", f"EOD complete: {len(resolved)} resolved, {len(alerts)} alerts")
    return result


def run_weekly() -> dict:
    """
    Monday 7:30 AM EST: Weekly review.
    - Full 100-ticker scan + learning review + roster evaluation
    - Uses Sonnet Batch API
    - Always sends weekly summary
    """
    events.agent_state("orch", "active")
    events.log("orch", "Starting weekly review")

    mem.init_db()
    ctx = _get_market_context()

    # Full scan
    candidates, watch_triggered, scan_reasoning = scanner.scan_all(
        regime=ctx["regime"], vix=ctx["vix"]
    )

    # The post-mortem agent walks over to the learning agent's desk to hand
    # off resolved-trade data for this week's ratchet review.
    events.agent_walk("pm", "learn", collab_ms=2000)

    # Learning review
    learning_review, learn_reasoning = learning_agent.weekly_review()

    # The roster agent walks back to the orchestrator with this week's
    # promotion / demotion proposals.
    events.agent_walk("roster", "orch", collab_ms=1800)

    # Roster evaluation
    roster_proposals, roster_reasoning = roster_agent.evaluate()

    result = {
        "type": "weekly",
        "timestamp": ctx["timestamp"],
        "regime": ctx["regime"],
        "vix": ctx["vix"],
        "candidates": candidates,
        "watch_triggered": watch_triggered,
        "learning_review": learning_review,
        "roster_proposals": roster_proposals,
        "reasoning": {
            "scanner": scan_reasoning,
            "learning": learn_reasoning,
            "roster": roster_reasoning,
        },
    }

    events.agent_state("orch", "done")
    events.log("orch", "Weekly review complete")
    return result
