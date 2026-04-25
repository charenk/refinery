"""Single source of truth for reading `memory/portfolio.json`.

Both the portfolio agent and the context builder go through `load_portfolio()`
so user-edited JSON is validated in one place and bad entries are dropped
with a warning instead of crashing a scan.

Validation rules:
  - `ticker`        non-empty string matching ^[A-Z][A-Z0-9.-]{0,15}$
                    (uppercased before checking; covers AAPL, BRK-B, SHOP.TO)
  - `shares`        non-negative number (int or float)
  - `avg_cost_cad`  non-negative number
  - `currency`      one of {"USD", "CAD"}; defaults to "CAD"
  - `exchange`      free-form string; defaults to "" (yfinance handles `.TO`
                    if the ticker already carries the suffix)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,15}$")
_ALLOWED_CURRENCIES = {"USD", "CAD"}


def _is_non_negative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _validate_holding(raw: dict, index: int) -> dict | None:
    """Return a sanitised holding dict, or None if it should be dropped."""
    if not isinstance(raw, dict):
        logger.warning("portfolio.json holding #%d is not an object; skipping", index)
        return None

    ticker = str(raw.get("ticker", "")).upper().strip()
    if not _TICKER_PATTERN.match(ticker):
        logger.warning("portfolio.json holding #%d has invalid ticker %r; skipping", index, ticker)
        return None

    shares = raw.get("shares", 0)
    if not _is_non_negative_number(shares):
        logger.warning("portfolio.json %s has invalid shares %r; skipping", ticker, shares)
        return None

    avg_cost_cad = raw.get("avg_cost_cad", 0)
    if not _is_non_negative_number(avg_cost_cad):
        logger.warning("portfolio.json %s has invalid avg_cost_cad %r; skipping", ticker, avg_cost_cad)
        return None

    currency = str(raw.get("currency", "CAD")).upper()
    if currency not in _ALLOWED_CURRENCIES:
        logger.warning(
            "portfolio.json %s has unsupported currency %r; coercing to CAD", ticker, currency
        )
        currency = "CAD"

    return {
        "ticker": ticker,
        "exchange": str(raw.get("exchange", "")),
        "currency": currency,
        "shares": float(shares),
        "avg_cost_cad": float(avg_cost_cad),
        "date_entered": raw.get("date_entered"),
        "target_cad": raw.get("target_cad"),
        "stop_cad": raw.get("stop_cad"),
        "notes": str(raw.get("notes", "")),
    }


def load_portfolio(portfolio_path: str | None = None) -> dict:
    """Read `memory/portfolio.json` and return a validated portfolio dict.

    Returns an empty-holdings dict if the file is missing or unreadable, so a
    fresh install does not crash the agents.
    """
    if portfolio_path is None:
        portfolio_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "memory",
            "portfolio.json",
        )

    empty = {
        "holdings": [],
        "cash_available": 0.0,
        "currency": "CAD",
        "account": "Personal",
    }

    try:
        with open(portfolio_path) as file_handle:
            raw = json.load(file_handle)
    except FileNotFoundError:
        logger.info("portfolio.json not found at %s; using empty portfolio", portfolio_path)
        return empty
    except json.JSONDecodeError as error:
        logger.error("portfolio.json is not valid JSON (%s); using empty portfolio", error)
        return empty

    if not isinstance(raw, dict):
        logger.error("portfolio.json must be a JSON object; using empty portfolio")
        return empty

    raw_holdings = raw.get("holdings", [])
    if not isinstance(raw_holdings, list):
        logger.error("portfolio.json `holdings` must be a list; using empty list")
        raw_holdings = []

    validated_holdings: list[dict] = []
    for index, raw_holding in enumerate(raw_holdings):
        cleaned = _validate_holding(raw_holding, index)
        if cleaned is not None and cleaned["shares"] > 0:
            validated_holdings.append(cleaned)

    cash_available = raw.get("cash_available", 0)
    if not _is_non_negative_number(cash_available):
        logger.warning("portfolio.json cash_available %r is invalid; coercing to 0", cash_available)
        cash_available = 0.0

    return {
        "last_updated": raw.get("last_updated"),
        "currency": str(raw.get("currency", "CAD")).upper(),
        "account": str(raw.get("account", "Personal")),
        "cash_available": float(cash_available),
        "holdings": validated_holdings,
    }
