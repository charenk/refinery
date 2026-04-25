from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import feedparser

logger = logging.getLogger(__name__)


def get_ohlcv(ticker: str, days: int = 90) -> pd.DataFrame:
    """Fetch OHLCV data from yfinance. Returns empty DataFrame on failure."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days + 10)  # buffer for weekends
        t = yf.Ticker(ticker)
        df = t.history(start=start.strftime("%Y-%m-%d"),
                       end=end.strftime("%Y-%m-%d"))
        if df.empty:
            logger.warning(f"No OHLCV data for {ticker}")
            return pd.DataFrame()
        # Standardize column names
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        return df.tail(days)
    except Exception as e:
        logger.error(f"get_ohlcv({ticker}) failed: {e}")
        return pd.DataFrame()


def get_news(ticker: str) -> list[dict]:
    """Fetch recent news from Yahoo Finance RSS. Returns list of {title, summary, published}."""
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:10]:
            results.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", ""),
            })
        return results
    except Exception as e:
        logger.error(f"get_news({ticker}) failed: {e}")
        return []


def get_earnings_calendar(ticker: str) -> datetime | None:
    """Get next earnings date for a ticker. Returns None if unavailable."""
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return None
        # yfinance returns calendar as dict or DataFrame depending on version
        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
            if earnings_date:
                if isinstance(earnings_date, list) and len(earnings_date) > 0:
                    return pd.Timestamp(earnings_date[0]).to_pydatetime()
                return pd.Timestamp(earnings_date).to_pydatetime()
        elif isinstance(cal, pd.DataFrame):
            if "Earnings Date" in cal.columns:
                val = cal["Earnings Date"].iloc[0]
                return pd.Timestamp(val).to_pydatetime()
        return None
    except Exception as e:
        logger.error(f"get_earnings_calendar({ticker}) failed: {e}")
        return None


def get_global_indices() -> dict:
    """Fetch current prices for global indices. Returns dict of {name: price}."""
    from config import GLOBAL_INDICES
    results = {}
    all_tickers = []
    for region, tickers in GLOBAL_INDICES.items():
        all_tickers.extend(tickers)
    try:
        data = yf.download(all_tickers, period="2d", progress=False, group_by="ticker")
        for ticker in all_tickers:
            try:
                if len(all_tickers) == 1:
                    close = data["Close"].iloc[-1]
                else:
                    close = data[ticker]["Close"].iloc[-1]
                results[ticker] = round(float(close), 2)
            except Exception:
                results[ticker] = None
    except Exception as e:
        logger.error(f"get_global_indices() failed: {e}")
    return results


def get_commodities() -> dict:
    """Fetch commodity prices. Returns dict of {ticker: price}."""
    from config import COMMODITIES
    results = {}
    try:
        data = yf.download(COMMODITIES, period="2d", progress=False, group_by="ticker")
        for ticker in COMMODITIES:
            try:
                close = data[ticker]["Close"].iloc[-1]
                results[ticker] = round(float(close), 2)
            except Exception:
                results[ticker] = None
    except Exception as e:
        logger.error(f"get_commodities() failed: {e}")
    return results


def get_fx_rates() -> dict:
    """Fetch FX rates. Returns dict of {pair: rate}."""
    from config import FX_PAIRS
    results = {}
    try:
        data = yf.download(FX_PAIRS, period="2d", progress=False, group_by="ticker")
        for pair in FX_PAIRS:
            try:
                if len(FX_PAIRS) == 1:
                    close = data["Close"].iloc[-1]
                else:
                    close = data[pair]["Close"].iloc[-1]
                results[pair] = round(float(close), 4)
            except Exception:
                results[pair] = None
    except Exception as e:
        logger.error(f"get_fx_rates() failed: {e}")
    return results
