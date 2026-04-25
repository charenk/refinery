from __future__ import annotations

import sqlite3
import json
import logging
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

import os as _os
DB_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "memory", "refinery.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id                  INTEGER PRIMARY KEY,
    date                TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    category            TEXT,
    setup_type          TEXT,
    quality_score       INTEGER,
    entry_low           REAL,
    entry_high          REAL,
    target_1            REAL,
    target_2            REAL,
    stop                REAL,
    rr_ratio            REAL,
    regime              TEXT,
    vix_at_signal       REAL,
    cadusd_at_signal    REAL,
    reasoning           TEXT,
    sentiment_score     INTEGER,
    outcome             TEXT DEFAULT 'pending',
    outcome_date        TEXT,
    exit_price          REAL,
    pnl_pct             REAL,
    post_mortem         TEXT,
    lessons_applied     TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pattern_knowledge (
    id                  INTEGER PRIMARY KEY,
    setup_type          TEXT NOT NULL,
    condition_key       TEXT NOT NULL,
    sample_size         INTEGER DEFAULT 0,
    win_rate            REAL,
    avg_rr              REAL,
    avg_hold_days       REAL,
    common_failures     TEXT,
    common_successes    TEXT,
    last_updated        TEXT,
    notes               TEXT,
    UNIQUE(setup_type, condition_key)
);

CREATE TABLE IF NOT EXISTS ticker_knowledge (
    id                  INTEGER PRIMARY KEY,
    ticker              TEXT UNIQUE NOT NULL,
    exchange            TEXT,
    last_updated        TEXT,
    key_levels          TEXT,
    earnings_behavior   TEXT,
    sector_correlation  TEXT,
    regime_behavior     TEXT,
    volume_profile      TEXT,
    ta_notes            TEXT,
    sentiment_notes     TEXT,
    personal_notes      TEXT,
    signal_count        INTEGER DEFAULT 0,
    win_rate            REAL,
    last_signal         TEXT,
    last_outcome        TEXT
);

CREATE TABLE IF NOT EXISTS regime_knowledge (
    id                  INTEGER PRIMARY KEY,
    regime_label        TEXT NOT NULL,
    date_range_start    TEXT,
    date_range_end      TEXT,
    description         TEXT,
    best_setups         TEXT,
    worst_setups        TEXT,
    best_categories     TEXT,
    worst_categories    TEXT,
    strategy_notes      TEXT,
    signal_count        INTEGER DEFAULT 0,
    win_rate            REAL
);

CREATE TABLE IF NOT EXISTS strategy_experiments (
    id                  INTEGER PRIMARY KEY,
    proposed_date       TEXT,
    parameter           TEXT,
    old_value           TEXT,
    new_value           TEXT,
    hypothesis          TEXT,
    trial_start         TEXT,
    trial_end           TEXT,
    baseline_winrate    REAL,
    trial_winrate       REAL,
    outcome             TEXT DEFAULT 'pending',
    revert_reason       TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS briefs (
    id                  INTEGER PRIMARY KEY,
    date                TEXT UNIQUE,
    regime              TEXT,
    n_setups            INTEGER,
    vix_level           REAL,
    cadusd              REAL,
    sp_futures_pct      REAL,
    win_rate_last_20    REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_ticker    ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_setup     ON trades(setup_type);
CREATE INDEX IF NOT EXISTS idx_trades_outcome   ON trades(outcome);
CREATE INDEX IF NOT EXISTS idx_trades_date      ON trades(date);
CREATE INDEX IF NOT EXISTS idx_pattern_setup    ON pattern_knowledge(setup_type);
CREATE INDEX IF NOT EXISTS idx_ticker_ticker    ON ticker_knowledge(ticker);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if not exists. Call on startup."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)


def save_signal(signal: dict) -> int:
    """Save a new signal. Returns trade_id.

    Skips insert if a signal for the same date+ticker already exists,
    returning the existing trade_id instead.
    """
    with get_conn() as conn:
        # Duplicate guard: same ticker on same date = skip
        existing = conn.execute(
            "SELECT id FROM trades WHERE date=? AND ticker=?",
            (signal["date"], signal["ticker"]),
        ).fetchone()
        if existing:
            logger.info(
                "Signal for %s on %s already exists (id=%d), skipping duplicate",
                signal["ticker"], signal["date"], existing["id"],
            )
            return existing["id"]

        cur = conn.execute(
            """INSERT INTO trades (date, ticker, category, setup_type, quality_score,
               entry_low, entry_high, target_1, target_2, stop, rr_ratio, regime,
               vix_at_signal, cadusd_at_signal, reasoning, sentiment_score, lessons_applied)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (signal["date"], signal["ticker"], signal["category"],
             signal["setup_type"], signal["quality_score"],
             signal["entry_low"], signal["entry_high"],
             signal["target_1"], signal["target_2"], signal["stop"],
             signal["rr_ratio"], signal["regime"],
             signal["vix_at_signal"], signal["cadusd_at_signal"],
             signal["reasoning"], signal["sentiment_score"],
             signal.get("lessons_applied", "")),
        )
        return cur.lastrowid


def update_outcome(trade_id: int, outcome: str, exit_price: float,
                   pnl_pct: float, post_mortem: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE trades SET outcome=?, outcome_date=?, exit_price=?,
               pnl_pct=?, post_mortem=? WHERE id=?""",
            (outcome, datetime.now().date().isoformat(),
             exit_price, pnl_pct, post_mortem, trade_id),
        )


def get_ticker_knowledge(ticker: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ticker_knowledge WHERE ticker=?", (ticker,)
        ).fetchone()
        return dict(row) if row else None


def upsert_ticker_knowledge(ticker: str, exchange: str, updates: dict) -> None:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM ticker_knowledge WHERE ticker=?", (ticker,)
        ).fetchone()
        if existing:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE ticker_knowledge SET {set_clause}, last_updated=? WHERE ticker=?",
                (*updates.values(), datetime.now().isoformat(), ticker),
            )
        else:
            cols = ["ticker", "exchange", "last_updated"] + list(updates.keys())
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)
            conn.execute(
                f"INSERT INTO ticker_knowledge ({col_names}) VALUES ({placeholders})",
                (ticker, exchange, datetime.now().isoformat(), *updates.values()),
            )


def get_pattern_knowledge(setup_type: str, condition_key: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pattern_knowledge WHERE setup_type=? AND condition_key=?",
            (setup_type, condition_key),
        ).fetchone()
        return dict(row) if row else None


def get_recent_signals(ticker: str | None = None, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        if ticker:
            rows = conn.execute(
                "SELECT * FROM trades WHERE ticker=? ORDER BY date DESC LIMIT ?",
                (ticker, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_pending_signals(expiry_days: int = 5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM trades WHERE outcome='pending'
               AND julianday('now') - julianday(date) <= ?""",
            (expiry_days,),
        ).fetchall()
        return [dict(r) for r in rows]


def save_reasoning_record(agent_name: str, ticker: str, record: str) -> None:
    """Save a reasoning record as a note in ticker_knowledge."""
    upsert_ticker_knowledge(ticker, "", {"ta_notes": record})


def get_win_rate(category: str | None = None, setup_type: str | None = None,
                 last_n: int = 20) -> float | None:
    """Calculate win rate from recent resolved trades."""
    with get_conn() as conn:
        query = "SELECT outcome FROM trades WHERE outcome != 'pending'"
        params = []
        if category:
            query += " AND category=?"
            params.append(category)
        if setup_type:
            query += " AND setup_type=?"
            params.append(setup_type)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(last_n)
        rows = conn.execute(query, params).fetchall()
        if not rows:
            return None
        wins = sum(1 for r in rows if r["outcome"] in ("hit_t1", "hit_t2"))
        return wins / len(rows)


def save_brief_record(date: str, regime: str, n_setups: int,
                      vix: float, cadusd: float, sp_futures_pct: float) -> None:
    """Record brief metadata."""
    win_rate = get_win_rate(last_n=20)
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO briefs
               (date, regime, n_setups, vix_level, cadusd, sp_futures_pct, win_rate_last_20)
               VALUES (?,?,?,?,?,?,?)""",
            (date, regime, n_setups, vix, cadusd, sp_futures_pct, win_rate),
        )
