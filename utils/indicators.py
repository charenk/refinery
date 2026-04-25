from __future__ import annotations

import logging

import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands

logger = logging.getLogger(__name__)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Add all configured indicators to OHLCV DataFrame. Returns df with new columns."""
    from config import TA as TA_CFG
    try:
        if df.empty or len(df) < 20:
            logger.warning("DataFrame too short for indicator computation")
            return df

        # EMAs
        for period in TA_CFG["ema_periods"]:
            df[f"ema_{period}"] = EMAIndicator(df["close"], window=period).ema_indicator()

        # RSI
        df["rsi"] = RSIIndicator(df["close"], window=TA_CFG["rsi_period"]).rsi()

        # ATR
        df["atr"] = AverageTrueRange(df["high"], df["low"], df["close"],
                                      window=TA_CFG["atr_period"]).average_true_range()

        # MACD
        macd = MACD(df["close"])
        df["MACD_12_26_9"] = macd.macd()
        df["MACDh_12_26_9"] = macd.macd_diff()
        df["MACDs_12_26_9"] = macd.macd_signal()

        # Bollinger Bands
        bb = BollingerBands(df["close"], window=20)
        df["BBU_20_2.0"] = bb.bollinger_hband()
        df["BBM_20_2.0"] = bb.bollinger_mavg()
        df["BBL_20_2.0"] = bb.bollinger_lband()

        # Volume SMA (20-day)
        df["vol_sma_20"] = df["volume"].rolling(window=20).mean()

        # ADX
        adx = ADXIndicator(df["high"], df["low"], df["close"], window=14)
        df["ADX_14"] = adx.adx()
        df["DMP_14"] = adx.adx_pos()
        df["DMN_14"] = adx.adx_neg()

        # Stochastic
        stoch = StochRSIIndicator(df["close"])
        df["STOCHRSIk_14_14_3_3"] = stoch.stochrsi_k()
        df["STOCHRSId_14_14_3_3"] = stoch.stochrsi_d()

    except Exception as e:
        logger.error(f"compute_all failed: {e}")
    return df


def get_ema_trend(df: pd.DataFrame) -> str:
    """Classify EMA alignment. Returns 'above_all', 'mixed', or 'below_all'."""
    try:
        if df.empty:
            return "mixed"
        last = df.iloc[-1]
        close = last["close"]
        emas = []
        for col in ["ema_9", "ema_20", "ema_50", "ema_200"]:
            if col in last and pd.notna(last[col]):
                emas.append(last[col])
        if not emas:
            return "mixed"
        if all(close > e for e in emas):
            return "above_all"
        if all(close < e for e in emas):
            return "below_all"
        return "mixed"
    except Exception as e:
        logger.error(f"get_ema_trend failed: {e}")
        return "mixed"


def get_key_levels(df: pd.DataFrame) -> dict:
    """Compute support, resistance, and pivot from recent price action."""
    try:
        if df.empty or len(df) < 5:
            return {"support": 0.0, "resistance": 0.0, "pivot": 0.0}

        recent = df.tail(20)
        high = recent["high"].max()
        low = recent["low"].min()
        close = df.iloc[-1]["close"]
        pivot = (high + low + close) / 3

        return {
            "support": round(low, 2),
            "resistance": round(high, 2),
            "pivot": round(pivot, 2),
        }
    except Exception as e:
        logger.error(f"get_key_levels failed: {e}")
        return {"support": 0.0, "resistance": 0.0, "pivot": 0.0}


def classify_regime(df: pd.DataFrame, vix: float | None = None) -> str:
    """Classify market regime from price data and VIX. Returns one of:
    'uptrend', 'downtrend', 'range', 'volatile'."""
    try:
        if df.empty or len(df) < 50:
            return "range"

        # Check VIX first: high volatility overrides trend
        if vix is not None and vix > 25:
            return "volatile"

        last = df.iloc[-1]

        # EMA trend
        ema_50 = last.get("ema_50")
        ema_200 = last.get("ema_200")
        close = last["close"]

        if pd.notna(ema_50) and pd.notna(ema_200):
            if close > ema_50 > ema_200:
                return "uptrend"
            if close < ema_50 < ema_200:
                return "downtrend"

        # ADX for trend strength
        adx_val = last.get("ADX_14")
        if pd.notna(adx_val) and adx_val < 20:
            return "range"

        # Fallback: 20-day return
        if len(df) >= 20:
            ret_20d = (close - df.iloc[-20]["close"]) / df.iloc[-20]["close"]
            if ret_20d > 0.05:
                return "uptrend"
            if ret_20d < -0.05:
                return "downtrend"

        return "range"
    except Exception as e:
        logger.error(f"classify_regime failed: {e}")
        return "range"
