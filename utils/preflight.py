"""Preflight validators for The Refinery.

This module is the single source of truth for "is this install ready to run".
Every validator returns `(ok: bool, message: str)` and never prints, so the
same code can be called from `check.py`, the interactive `setup.sh` wizard,
and the `run_or_die()` gate at the top of every run script.

Validators:
  validate_anthropic_key        sends a real 1-token Claude ping
  validate_smtp                 connects + auths to Gmail SMTP, optional send
  validate_portfolio            schema-checks memory/portfolio.json
  validate_db                   confirms the SQLite tables exist

Convenience:
  collect_results               runs all validators and returns a list of dicts
  run_or_die                    quick-fail entry point used by run_*.py
"""

from __future__ import annotations

import json
import os
import smtplib
import sqlite3
import sys
import time
from email.mime.text import MIMEText
from typing import Any

EXPECTED_TABLES = {
    "trades",
    "ticker_knowledge",
    "pattern_knowledge",
    "regime_knowledge",
    "strategy_experiments",
    "briefs",
}


# ─── Individual validators ───────────────────────────────────────────────────

def validate_anthropic_key(key: str | None) -> tuple[bool, str]:
    """Send a 1-token Haiku ping. Returns (ok, message)."""
    if not key or not key.strip():
        return False, "ANTHROPIC_API_KEY is not set"
    if not key.startswith("sk-ant-"):
        return False, "ANTHROPIC_API_KEY does not look like an Anthropic key (expected sk-ant-...)"

    try:
        import anthropic
    except ImportError:
        return False, "anthropic package is not installed; run ./setup.sh"

    try:
        client = anthropic.Anthropic(api_key=key)
        start = time.time()
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "."}],
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return True, f"Claude responded in {elapsed_ms} ms"
    except anthropic.AuthenticationError:
        return False, "Anthropic rejected the key (authentication failed)"
    except anthropic.RateLimitError:
        return True, "Key is valid but rate-limited (treating as ok)"
    except anthropic.APIConnectionError as error:
        return False, f"Network error reaching Anthropic: {error}"
    except Exception as error:
        return False, f"Unexpected error from Anthropic: {error}"


def validate_smtp(
    user: str | None,
    password: str | None,
    recipient: str | None,
    host: str = "smtp.gmail.com",
    port: int = 587,
    send_test: bool = False,
) -> tuple[bool, str]:
    """Verify SMTP credentials. Optionally send a one-line test email."""
    if not user or not user.strip():
        return False, "SMTP_USER is not set"
    if not password or not password.strip():
        return False, "SMTP_PASSWORD is not set"
    if not recipient or not recipient.strip():
        return False, "TO_EMAIL is not set"

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            if send_test:
                message = MIMEText(
                    "The Refinery is configured. This is the one-time test email "
                    "sent by ./setup.sh or `python check.py --send-email`."
                )
                message["Subject"] = "Refinery: configuration verified"
                message["From"] = user
                message["To"] = recipient
                server.sendmail(user, recipient, message.as_string())
                return True, f"Connected, authenticated, and sent test email to {recipient}"
            return True, f"Connected and authenticated as {user}"
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP rejected the credentials (use a Gmail App Password, not your main password)"
    except smtplib.SMTPConnectError as error:
        return False, f"Could not connect to {host}:{port} ({error})"
    except OSError as error:
        return False, f"Network error reaching {host}: {error}"
    except Exception as error:
        return False, f"Unexpected SMTP error: {error}"


def validate_portfolio(path: str | None = None) -> tuple[bool, str]:
    """Schema-check memory/portfolio.json. Returns (ok, message)."""
    from utils.portfolio_loader import load_portfolio

    portfolio = load_portfolio(path)
    holdings = portfolio.get("holdings", [])
    if not holdings:
        return True, "no holdings yet (add one before running scans)"
    return True, f"{len(holdings)} holding{'s' if len(holdings) != 1 else ''} loaded"


def validate_db(db_path: str | None = None) -> tuple[bool, str]:
    """Confirm the SQLite file exists and has all expected tables."""
    if db_path is None:
        from config import MEMORY
        db_path = MEMORY["db_path"]

    if not os.path.exists(db_path):
        return False, f"{db_path} does not exist (run ./setup.sh)"

    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
    except sqlite3.Error as error:
        return False, f"SQLite error reading {db_path}: {error}"

    actual_tables = {row[0] for row in rows}
    missing = EXPECTED_TABLES - actual_tables
    if missing:
        return False, f"missing tables: {', '.join(sorted(missing))}"
    return True, f"{len(EXPECTED_TABLES)}/{len(EXPECTED_TABLES)} tables present"


# ─── Aggregate ──────────────────────────────────────────────────────────────

def collect_results(send_email: bool = False) -> list[dict[str, Any]]:
    """Run every validator and return a list of result dicts.

    Each dict has keys: name, ok, message, skipped (bool).
    Used by check.py to render the checklist.
    """
    from dotenv import load_dotenv
    load_dotenv()

    env_exists = os.path.exists(".env")
    results: list[dict[str, Any]] = [
        {"name": ".env file", "ok": env_exists, "message": "exists" if env_exists else "missing", "skipped": False},
    ]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    ok, msg = validate_anthropic_key(api_key)
    results.append({"name": "ANTHROPIC_API_KEY", "ok": ok, "message": msg, "skipped": False})

    if send_email:
        ok, msg = validate_smtp(
            os.environ.get("SMTP_USER"),
            os.environ.get("SMTP_PASSWORD"),
            os.environ.get("TO_EMAIL"),
            send_test=True,
        )
        results.append({"name": "SMTP credentials", "ok": ok, "message": msg, "skipped": False})
    else:
        results.append({
            "name": "SMTP credentials",
            "ok": True,
            "message": "use --send-email to verify, otherwise skipped",
            "skipped": True,
        })

    ok, msg = validate_portfolio()
    results.append({"name": "memory/portfolio.json", "ok": ok, "message": msg, "skipped": False})

    ok, msg = validate_db()
    results.append({"name": "memory/refinery.db", "ok": ok, "message": msg, "skipped": False})

    return results


# ─── Quick-fail gate for run scripts ────────────────────────────────────────

def run_or_die(
    require_anthropic: bool = True,
    require_smtp: bool = True,
    require_anthropic_live: bool = False,
    require_db: bool = True,
) -> None:
    """Validate prerequisites at the top of `main()`. Exits with code 2 on failure.

    Defaults are tuned for the production run scripts: cheap checks only (no
    live API ping), but every required env var must be present and the DB
    must exist. Set `require_anthropic_live=True` to spend an API call.
    """
    from dotenv import load_dotenv
    load_dotenv()

    failures: list[str] = []

    if require_anthropic:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key or not api_key.strip():
            failures.append("ANTHROPIC_API_KEY is not set in .env")
        elif not api_key.startswith("sk-ant-"):
            failures.append("ANTHROPIC_API_KEY does not look like an Anthropic key")
        elif require_anthropic_live:
            ok, msg = validate_anthropic_key(api_key)
            if not ok:
                failures.append(f"Anthropic key rejected: {msg}")

    if require_smtp:
        if not os.environ.get("SMTP_USER", "").strip():
            failures.append("SMTP_USER is not set in .env")
        if not os.environ.get("SMTP_PASSWORD", "").strip():
            failures.append("SMTP_PASSWORD is not set in .env")
        if not os.environ.get("TO_EMAIL", "").strip():
            failures.append("TO_EMAIL is not set in .env")

    if require_db:
        ok, msg = validate_db()
        if not ok:
            failures.append(f"Database: {msg}")

    if failures:
        sys.stderr.write("Refinery preflight failed:\n")
        for failure in failures:
            sys.stderr.write(f"  - {failure}\n")
        sys.stderr.write("\nRun 'python check.py' for details, or './setup.sh' to (re)configure.\n")
        sys.exit(2)
