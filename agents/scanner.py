"""
Scanner agent: rule-based screening of candidate tickers.

Active tier (top 4 per category): full screening with quality scoring.
Watch tier (remaining 6 per category): trigger-based only.

No Claude API calls. Pure rule-based filtering using indicators and config thresholds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from agents import memory_agent as mem
from utils import data_fetcher, indicators
from utils.context_builder import build_scanner_context
from ui import events

logger = logging.getLogger(__name__)


def _is_canadian(ticker: str) -> bool:
    return ticker.endswith(".TO")


def _passes_filters(ticker: str, df: pd.DataFrame, earnings_date) -> tuple[bool, str]:
    """Apply basic filters. Returns (passes, reason_if_rejected)."""
    from config import SCANNER

    if df.empty or len(df) < 20:
        return False, "insufficient data"

    last = df.iloc[-1]
    close = last["close"]

    # Price filter
    min_price = SCANNER["min_price_ca"] if _is_canadian(ticker) else SCANNER["min_price_us"]
    if close < min_price:
        return False, f"price ${close:.2f} below min ${min_price}"

    # Volume filter (20-day average)
    vol_sma = last.get("vol_sma_20")
    if pd.notna(vol_sma) and vol_sma < SCANNER["min_avg_volume"]:
        return False, f"avg volume {vol_sma:.0f} below {SCANNER['min_avg_volume']}"

    # RSI filter
    rsi = last.get("rsi")
    if pd.notna(rsi):
        if rsi < SCANNER["rsi_min"] or rsi > SCANNER["rsi_max"]:
            return False, f"RSI {rsi:.1f} outside [{SCANNER['rsi_min']}, {SCANNER['rsi_max']}]"

    # Earnings proximity filter
    if earnings_date:
        days_to_earnings = (earnings_date - datetime.now()).days
        if 0 <= days_to_earnings <= SCANNER["earnings_avoid_days"]:
            return False, f"earnings in {days_to_earnings} days"

    return True, ""


def _classify_setup(df: pd.DataFrame) -> str:
    """Classify the dominant setup type from current price action."""
    if df.empty or len(df) < 20:
        return "momentum"

    last = df.iloc[-1]
    close = last["close"]
    ema_trend = indicators.get_ema_trend(df)

    rsi = last.get("rsi", 50)
    atr = last.get("atr", 0)
    levels = indicators.get_key_levels(df)

    # Breakout: price near/above resistance with volume
    resistance = levels["resistance"]
    if resistance > 0 and close >= resistance * 0.995:
        vol = last.get("volume", 0)
        vol_sma = last.get("vol_sma_20", vol)
        if pd.notna(vol_sma) and vol_sma > 0 and vol > vol_sma * 1.3:
            return "breakout"

    # Pullback: uptrend but price pulled back to EMA support
    ema_20 = last.get("ema_20")
    ema_50 = last.get("ema_50")
    if ema_trend == "above_all" or (pd.notna(ema_50) and close > ema_50):
        if pd.notna(ema_20) and close <= ema_20 * 1.01:
            return "pullback"

    # Reversal: oversold bounce signals
    if pd.notna(rsi) and rsi < 45:
        support = levels["support"]
        if support > 0 and close <= support * 1.02:
            return "reversal"

    # Default: momentum
    return "momentum"


def _score_quality(df: pd.DataFrame, setup_type: str, regime: str) -> int:
    """Score setup quality from 1-5 based on multiple factors."""
    if df.empty:
        return 1

    score = 2  # base score
    last = df.iloc[-1]

    # EMA alignment bonus
    ema_trend = indicators.get_ema_trend(df)
    if setup_type in ("breakout", "momentum") and ema_trend == "above_all":
        score += 1
    elif setup_type == "reversal" and ema_trend == "below_all":
        score += 1
    elif setup_type == "pullback" and ema_trend in ("above_all", "mixed"):
        score += 1

    # Volume confirmation
    vol = last.get("volume", 0)
    vol_sma = last.get("vol_sma_20", vol)
    if pd.notna(vol_sma) and vol_sma > 0 and vol > vol_sma * 1.5:
        score += 1

    # ADX trend strength
    adx = last.get("ADX_14")
    if pd.notna(adx) and adx > 25:
        score += 1

    # Regime alignment penalty
    if regime == "volatile" and setup_type in ("breakout", "momentum"):
        score -= 1
    if regime == "downtrend" and setup_type in ("breakout", "momentum"):
        score -= 1

    return max(1, min(5, score))


def _compute_rr(df: pd.DataFrame, setup_type: str) -> dict:
    """Compute entry zone, targets, stop, and R:R ratio."""
    from config import TA as TA_CFG

    last = df.iloc[-1]
    close = last["close"]
    atr = last.get("atr", close * 0.02)
    if pd.isna(atr) or atr <= 0:
        atr = close * 0.02

    levels = indicators.get_key_levels(df)
    multiplier = TA_CFG["stop_atr_multiplier"]

    if setup_type == "breakout":
        entry_low = round(close * 0.998, 2)
        entry_high = round(close * 1.005, 2)
        stop = round(close - atr * multiplier, 2)
        target_1 = round(close + atr * 2, 2)
        target_2 = round(close + atr * 3.5, 2)
    elif setup_type == "pullback":
        ema_20 = last.get("ema_20", close)
        if pd.isna(ema_20):
            ema_20 = close
        entry_low = round(min(close, ema_20) * 0.998, 2)
        entry_high = round(close * 1.003, 2)
        stop = round(close - atr * multiplier, 2)
        target_1 = round(levels["resistance"], 2) if levels["resistance"] > close else round(close + atr * 2, 2)
        target_2 = round(close + atr * 3, 2)
    elif setup_type == "reversal":
        entry_low = round(levels["support"] * 0.998, 2) if levels["support"] > 0 else round(close * 0.995, 2)
        entry_high = round(close * 1.005, 2)
        stop = round(levels["support"] - atr * multiplier, 2) if levels["support"] > 0 else round(close - atr * multiplier, 2)
        target_1 = round(levels["pivot"], 2) if levels["pivot"] > close else round(close + atr * 1.5, 2)
        target_2 = round(close + atr * 3, 2)
    else:  # momentum
        entry_low = round(close * 0.997, 2)
        entry_high = round(close * 1.003, 2)
        stop = round(close - atr * multiplier, 2)
        target_1 = round(close + atr * 1.5, 2)
        target_2 = round(close + atr * 2.5, 2)

    risk = close - stop
    reward = target_1 - close
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "target_1": target_1,
        "target_2": target_2,
        "stop": stop,
        "rr_ratio": rr_ratio,
    }


def _build_reasoning(ticker: str, setup_type: str, quality: int, df: pd.DataFrame,
                     regime: str, filter_notes: str) -> str:
    """Build a reasoning record for this scan result."""
    last = df.iloc[-1]
    parts = [
        f"Scanner reasoning for {ticker} ({setup_type}, quality {quality}/5):",
        f"  Regime: {regime}",
        f"  Close: ${last['close']:.2f}",
    ]

    rsi = last.get("rsi")
    if pd.notna(rsi):
        parts.append(f"  RSI: {rsi:.1f}")

    ema_trend = indicators.get_ema_trend(df)
    parts.append(f"  EMA alignment: {ema_trend}")

    adx = last.get("ADX_14")
    if pd.notna(adx):
        parts.append(f"  ADX: {adx:.1f}")

    vol = last.get("volume", 0)
    vol_sma = last.get("vol_sma_20", 0)
    if pd.notna(vol_sma) and vol_sma > 0:
        parts.append(f"  Volume ratio: {vol / vol_sma:.1f}x avg")

    if filter_notes:
        parts.append(f"  Notes: {filter_notes}")

    return "\n".join(parts)


def scan_active_tier(
    category: str,
    tickers: list[str],
    regime: str,
    vix: float | None = None,
) -> tuple[list[dict], str]:
    """
    Scan active tier tickers (top 4 per category) with full screening.

    Returns:
        (candidates, reasoning_record)
        candidates: list of dicts with ticker, category, setup_type, quality_score,
                    entry/target/stop levels, rr_ratio, and reasoning
        reasoning_record: summary of scan for this category
    """
    from config import SCANNER

    events.agent_state("scan", "active")
    events.log("scan", f"Scanning {category}: {len(tickers)} active tickers")

    context = build_scanner_context(category, regime)
    candidates = []
    scan_notes = [f"Active scan: {category} ({regime})", f"Memory context: {context[:200]}"]

    for ticker in tickers:
        try:
            df = data_fetcher.get_ohlcv(ticker)
            if df.empty:
                scan_notes.append(f"  {ticker}: skipped (no data)")
                continue

            df = indicators.compute_all(df)
            earnings = data_fetcher.get_earnings_calendar(ticker)

            passes, reject_reason = _passes_filters(ticker, df, earnings)
            if not passes:
                scan_notes.append(f"  {ticker}: filtered ({reject_reason})")
                continue

            setup_type = _classify_setup(df)
            quality = _score_quality(df, setup_type, regime)

            if quality < SCANNER["min_quality_score"]:
                scan_notes.append(f"  {ticker}: quality {quality}/5 below min {SCANNER['min_quality_score']}")
                continue

            levels = _compute_rr(df, setup_type)

            # R:R filter: reject setups where risk outweighs reward
            min_rr = SCANNER.get("min_rr_ratio", 0)
            if min_rr > 0 and levels["rr_ratio"] < min_rr:
                scan_notes.append(f"  {ticker}: R:R {levels['rr_ratio']} below min {min_rr}")
                continue
            reasoning = _build_reasoning(ticker, setup_type, quality, df, regime, "")

            candidate = {
                "ticker": ticker,
                "category": category,
                "setup_type": setup_type,
                "quality_score": quality,
                "regime": regime,
                "close": round(float(df.iloc[-1]["close"]), 2),
                "reasoning": reasoning,
                **levels,
            }
            candidates.append(candidate)
            scan_notes.append(f"  {ticker}: {setup_type} quality {quality}/5 R:R {levels['rr_ratio']}")

            events.log("scan", f"{ticker}: {setup_type} q{quality} R:R {levels['rr_ratio']}")

        except Exception as e:
            logger.error(f"scan_active_tier: {ticker} failed: {e}")
            scan_notes.append(f"  {ticker}: error ({e})")

    # Sort by quality descending, then R:R descending as tiebreaker
    candidates.sort(key=lambda c: (c["quality_score"], c["rr_ratio"]), reverse=True)

    reasoning_record = "\n".join(scan_notes)
    events.agent_state("scan", "done")
    return candidates, reasoning_record


def scan_watch_tier(
    category: str,
    tickers: list[str],
    regime: str,
) -> tuple[list[dict], str]:
    """
    Scan watch tier tickers (remaining 6 per category) with trigger-based checks only.
    Only flags tickers that hit a watch tier trigger condition.

    Returns:
        (triggered, reasoning_record)
        triggered: list of dicts for tickers that hit a trigger
        reasoning_record: summary
    """
    from config import WATCH_TIER_TRIGGERS

    events.log("scan", f"Watch tier: {category} ({len(tickers)} tickers)")

    triggered = []
    scan_notes = [f"Watch tier scan: {category} ({regime})"]

    for ticker in tickers:
        try:
            df = data_fetcher.get_ohlcv(ticker, days=30)
            if df.empty or len(df) < 10:
                continue

            df = indicators.compute_all(df)
            last = df.iloc[-1]
            close = last["close"]
            triggers_hit = []

            # Trigger 1: EMA20 crossover in last N days
            lookback = WATCH_TIER_TRIGGERS["ema20_cross_lookback_days"]
            ema_20_col = "ema_20"
            if ema_20_col in df.columns and len(df) > lookback:
                recent = df.tail(lookback)
                for i in range(1, len(recent)):
                    prev = recent.iloc[i - 1]
                    curr = recent.iloc[i]
                    if (pd.notna(prev.get(ema_20_col)) and pd.notna(curr.get(ema_20_col))
                            and prev["close"] < prev[ema_20_col]
                            and curr["close"] > curr[ema_20_col]):
                        triggers_hit.append("ema20_cross_above")
                        break

            # Trigger 2: Volume spike
            vol = last.get("volume", 0)
            vol_sma = last.get("vol_sma_20", 0)
            if pd.notna(vol_sma) and vol_sma > 0:
                ratio = vol / vol_sma
                if ratio >= WATCH_TIER_TRIGGERS["volume_ratio_threshold"]:
                    triggers_hit.append(f"volume_spike_{ratio:.1f}x")

            # Trigger 3: Near resistance
            levels = indicators.get_key_levels(df)
            if levels["resistance"] > 0:
                proximity = (levels["resistance"] - close) / levels["resistance"]
                if 0 <= proximity <= WATCH_TIER_TRIGGERS["resistance_proximity_pct"]:
                    triggers_hit.append("near_resistance")

            # Trigger 4: RSI crossing above 50
            rsi = last.get("rsi")
            if pd.notna(rsi) and len(df) >= 2:
                prev_rsi = df.iloc[-2].get("rsi")
                if pd.notna(prev_rsi):
                    cross_level = WATCH_TIER_TRIGGERS["rsi_cross_level"]
                    if prev_rsi < cross_level <= rsi:
                        triggers_hit.append("rsi_cross_50")

            if triggers_hit:
                triggered.append({
                    "ticker": ticker,
                    "category": category,
                    "triggers": triggers_hit,
                    "close": round(float(close), 2),
                    "rsi": round(float(rsi), 1) if pd.notna(rsi) else None,
                })
                scan_notes.append(f"  {ticker}: TRIGGERED [{', '.join(triggers_hit)}]")
            else:
                scan_notes.append(f"  {ticker}: no triggers")

        except Exception as e:
            logger.error(f"scan_watch_tier: {ticker} failed: {e}")
            scan_notes.append(f"  {ticker}: error ({e})")

    reasoning_record = "\n".join(scan_notes)
    return triggered, reasoning_record


def scan_all(
    regime: str,
    vix: float | None = None,
    active_only: bool = False,
) -> tuple[list[dict], list[dict], str]:
    """
    Full scan across all categories.

    Args:
        regime: current market regime
        vix: current VIX level
        active_only: if True, skip watch tier scanning

    Returns:
        (active_candidates, watch_triggered, full_reasoning_record)
    """
    from config import CANDIDATE_POOLS, ROSTER

    events.agent_state("scan", "active")
    mem.init_db()

    active_per_cat = ROSTER["active_tier_per_category"]
    all_active = []
    all_watch = []
    all_reasoning = [
        f"Full scan at {datetime.now().isoformat()}",
        f"Regime: {regime} | VIX: {vix}",
        "",
    ]

    for category, tickers in CANDIDATE_POOLS.items():
        active_tickers = tickers[:active_per_cat]
        watch_tickers = tickers[active_per_cat:]

        # Active tier
        candidates, reasoning = scan_active_tier(category, active_tickers, regime, vix)
        all_active.extend(candidates)
        all_reasoning.append(reasoning)

        # Watch tier
        if not active_only and watch_tickers:
            triggered, w_reasoning = scan_watch_tier(category, watch_tickers, regime)
            all_watch.extend(triggered)
            all_reasoning.append(w_reasoning)

    # Sort all active candidates by quality, then R:R as tiebreaker
    all_active.sort(key=lambda c: (c["quality_score"], c["rr_ratio"]), reverse=True)

    full_reasoning = "\n\n".join(all_reasoning)

    # Save reasoning record
    mem.save_reasoning_record("scanner", "SCAN", full_reasoning[:2000])

    events.agent_state("scan", "done")
    events.scan_complete()
    events.log("scan", f"Complete: {len(all_active)} candidates, {len(all_watch)} watch triggers")

    return all_active, all_watch, full_reasoning
