"""Flask + Socket.IO server for The Refinery dashboard.

Serves five tabs at http://127.0.0.1:5173 by default:

  Office       Pixel-art room where eight agents animate during a live scan.
  Morning Report   The latest brief that the system produced.
  Portfolio    Your current holdings with live prices and unrealised PnL.
  Roster       The 100-ticker watchlist organised into ten categories.
  Performance  Win-rate and signal-history charts.

Security defaults:
  - Binds to 127.0.0.1 only. To expose on the local network, set
    REFINERY_UI_HOST=0.0.0.0 in the environment. (Anyone on the same Wi-Fi
    can then read your portfolio and trigger scans, so know what you are
    opting into.)
  - The trigger_scan socket event runs only the in-process orchestrator. It
    does NOT spawn arbitrary subprocesses based on user input.
"""

import glob as glob_module
import json
import logging
import os
import sys

from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit

# Make the parent directory importable so `from agents` etc. work when this
# file is run directly (`python ui/app.py`).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents import memory_agent
from ui import events

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
PORTFOLIO_PATH = os.path.join(REPO_ROOT, "memory", "portfolio.json")
ROSTER_PATH = os.path.join(REPO_ROOT, "memory", "roster.json")
OUTPUTS_DIR = os.path.join(REPO_ROOT, "outputs")

ALLOWED_SCAN_TYPES = {"daily", "overnight", "open_watch", "midday", "eod", "pulse", "weekly"}

app = Flask(__name__, static_folder="static", static_url_path="", template_folder="static")
# Per-process secret. Sessions do not survive restarts, which is fine for a
# local-only single-user dashboard.
app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Register the socket instance so agents can emit events into the UI.
events.register(socketio)


def _read_json_or_default(path: str, default: dict) -> dict:
    """Read a JSON file. Return `default` if the file is missing or unreadable."""
    try:
        with open(path) as file_handle:
            return json.load(file_handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: str, data: dict) -> None:
    """Write JSON to `path` with indentation. Parent directory must exist."""
    with open(path, "w") as file_handle:
        json.dump(data, file_handle, indent=2)


def _update_env_file(updates: dict[str, str]) -> str:
    """Atomically update `.env` with the given key->value pairs.

    Preserves all existing keys, comments, and ordering. Adds new keys at
    the end. Writes to a temp file then renames so a crash mid-write never
    leaves a partial .env. Sets mode 600 on the result.

    Returns the absolute path of the .env file written.
    """
    import tempfile

    env_path = os.path.abspath(os.path.join(REPO_ROOT, ".env"))
    existing_lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path) as file_handle:
            existing_lines = file_handle.readlines()

    # Walk lines: replace any key in updates, preserve everything else.
    seen_keys: set[str] = set()
    new_lines: list[str] = []
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(raw_line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            seen_keys.add(key)
        else:
            new_lines.append(raw_line)

    # Append any keys that weren't already present.
    for key, value in updates.items():
        if key not in seen_keys:
            new_lines.append(f"{key}={value}\n")

    # Atomic write: temp file in the same directory, then rename.
    fd, tmp_path = tempfile.mkstemp(prefix=".env.", dir=os.path.dirname(env_path))
    try:
        with os.fdopen(fd, "w") as tmp_handle:
            tmp_handle.writelines(new_lines)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, env_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return env_path


# Tab routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def serve_index():
    return app.send_static_file("index.html")


@app.route("/api/onboarding/status")
def api_onboarding_status():
    """Per-step onboarding state for the Setup tab.

    Returns presence flags only (no live API/SMTP pings, those happen on
    Validate-and-Save). Never throws.
    """
    from dotenv import load_dotenv
    from utils.portfolio_loader import load_portfolio

    # Reload .env each call so the Setup tab sees writes immediately.
    load_dotenv(override=True)

    env_path = os.path.abspath(os.path.join(REPO_ROOT, ".env"))
    has_env = os.path.exists(env_path)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    has_anthropic_key = bool(anthropic_key) and anthropic_key.startswith("sk-ant-")

    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    to_email = os.environ.get("TO_EMAIL", "").strip()
    has_smtp = bool(smtp_user and smtp_password and to_email)

    validated = load_portfolio(PORTFOLIO_PATH)
    has_holdings = bool(validated.get("holdings"))

    has_briefs = bool(glob_module.glob(os.path.join(OUTPUTS_DIR, "*_brief.md")))

    return jsonify({
        "has_env": has_env,
        "has_anthropic_key": has_anthropic_key,
        "has_smtp": has_smtp,
        "has_holdings": has_holdings,
        "has_briefs": has_briefs,
        "env_path": env_path,
        "smtp_user": smtp_user if has_smtp else "",
        "to_email": to_email if has_smtp else "",
    })


# API endpoints (consumed by the JS tabs) ─────────────────────────────────────

@app.route("/api/portfolio")
def api_portfolio():
    portfolio = _read_json_or_default(
        PORTFOLIO_PATH,
        {"holdings": [], "cash_available": 0, "currency": "CAD", "_note": "Create memory/portfolio.json from memory/portfolio.example.json."},
    )
    return jsonify(portfolio)


@app.route("/api/roster")
def api_roster():
    roster = _read_json_or_default(
        ROSTER_PATH,
        {"categories": {}, "pending_changes": [], "_note": "Roster will be initialized on first scan."},
    )
    return jsonify(roster)


@app.route("/api/signals")
def api_signals():
    limit = request.args.get("limit", default=50, type=int)
    rows = memory_agent.get_recent_signals(limit=limit)
    return jsonify(rows)


@app.route("/api/brief/latest")
def api_brief_latest():
    files = sorted(glob_module.glob(os.path.join(OUTPUTS_DIR, "*_brief.md")), reverse=True)
    if not files:
        return jsonify({"content": "No briefs yet. Run `python run_daily.py` to generate one."})
    with open(files[0]) as file_handle:
        return jsonify({"date": os.path.basename(files[0]), "content": file_handle.read()})


@app.route("/api/briefs")
def api_briefs():
    files = sorted(glob_module.glob(os.path.join(OUTPUTS_DIR, "*_brief.md")), reverse=True)
    return jsonify([os.path.basename(f) for f in files])


@app.route("/api/brief/<filename>")
def api_brief_by_name(filename: str):
    # Reject any path traversal.
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return jsonify({"error": "Invalid filename"}), 400
    path = os.path.join(OUTPUTS_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "Brief not found"}), 404
    with open(path) as file_handle:
        return jsonify({"date": filename, "content": file_handle.read()})


@app.route("/api/roster/approve", methods=["POST"])
def api_roster_approve():
    data = request.json or {}
    roster = _read_json_or_default(ROSTER_PATH, {"pending_changes": []})
    for change in roster.get("pending_changes", []):
        if change.get("evict") == data.get("evict"):
            change["status"] = "approved"
    _write_json(ROSTER_PATH, roster)
    return jsonify({"ok": True})


@app.route("/api/roster/reject", methods=["POST"])
def api_roster_reject():
    data = request.json or {}
    roster = _read_json_or_default(ROSTER_PATH, {"pending_changes": []})
    roster["pending_changes"] = [
        change for change in roster.get("pending_changes", [])
        if change.get("evict") != data.get("evict")
    ]
    _write_json(ROSTER_PATH, roster)
    return jsonify({"ok": True})


@app.route("/api/roster/add", methods=["POST"])
def api_roster_add():
    data = request.json or {}
    ticker = str(data.get("ticker", "")).upper().strip()
    category = str(data.get("category", "")).strip()
    if not ticker or not category:
        return jsonify({"error": "ticker and category are required"}), 400
    roster = _read_json_or_default(ROSTER_PATH, {"categories": {}})
    cat = roster.get("categories", {}).get(category)
    if not cat:
        return jsonify({"error": "Invalid category"}), 400
    if ticker not in cat.get("tickers", []):
        cat.setdefault("tickers", []).append(ticker)
        cat.setdefault("watch_tier", []).append(ticker)
    _write_json(ROSTER_PATH, roster)
    return jsonify({"ok": True})


@app.route("/api/roster/remove", methods=["POST"])
def api_roster_remove():
    data = request.json or {}
    ticker = str(data.get("ticker", "")).upper().strip()
    category = str(data.get("category", "")).strip()
    roster = _read_json_or_default(ROSTER_PATH, {"categories": {}})
    cat = roster.get("categories", {}).get(category)
    if cat:
        for tier_key in ("tickers", "active_tier", "watch_tier"):
            if ticker in cat.get(tier_key, []):
                cat[tier_key].remove(ticker)
    _write_json(ROSTER_PATH, roster)
    return jsonify({"ok": True})


@app.route("/api/roster/pin", methods=["POST"])
def api_roster_pin():
    data = request.json or {}
    ticker = str(data.get("ticker", "")).upper().strip()
    category = str(data.get("category", "")).strip()
    roster = _read_json_or_default(ROSTER_PATH, {"categories": {}})
    cat = roster.get("categories", {}).get(category)
    if cat:
        cat.setdefault("pinned", [])
        if ticker not in cat["pinned"]:
            cat["pinned"].append(ticker)
    _write_json(ROSTER_PATH, roster)
    return jsonify({"ok": True})


@app.route("/api/onboarding/credentials/anthropic", methods=["POST"])
def api_onboarding_anthropic():
    """Validate and persist the Anthropic API key.

    Calls validate_anthropic_key (live 1-token ping) before writing. The key
    is never echoed back in the response.
    """
    from utils.preflight import validate_anthropic_key

    api_key = str((request.json or {}).get("api_key", "")).strip()
    if not api_key:
        return jsonify({"ok": False, "error": "API key is required."}), 400

    ok, message = validate_anthropic_key(api_key)
    if not ok:
        return jsonify({"ok": False, "error": message}), 400

    try:
        _update_env_file({"ANTHROPIC_API_KEY": api_key})
    except Exception as error:
        return jsonify({"ok": False, "error": f"Could not write .env: {error}"}), 500

    return jsonify({"ok": True, "message": message})


@app.route("/api/onboarding/credentials/smtp", methods=["POST"])
def api_onboarding_smtp():
    """Validate and persist Gmail SMTP credentials.

    Connects + authenticates against Gmail before writing. Sends a one-line
    test email so the user knows it actually reached their inbox.
    """
    from utils.preflight import validate_smtp

    body = request.json or {}
    smtp_user = str(body.get("smtp_user", "")).strip()
    smtp_password = str(body.get("smtp_password", "")).strip()
    to_email = str(body.get("to_email", "")).strip() or smtp_user

    if not (smtp_user and smtp_password and to_email):
        return jsonify({"ok": False, "error": "Gmail address, App Password, and recipient are all required."}), 400

    send_test = bool(body.get("send_test", True))
    ok, message = validate_smtp(smtp_user, smtp_password, to_email, send_test=send_test)
    if not ok:
        return jsonify({"ok": False, "error": message}), 400

    try:
        _update_env_file({
            "SMTP_USER": smtp_user,
            "SMTP_PASSWORD": smtp_password,
            "TO_EMAIL": to_email,
        })
    except Exception as error:
        return jsonify({"ok": False, "error": f"Could not write .env: {error}"}), 500

    return jsonify({"ok": True, "message": message})


@app.route("/api/onboarding/scan", methods=["POST"])
def api_onboarding_scan():
    """Trigger the morning scan from the Setup tab. Same as the Office button."""
    def execute_scan():
        try:
            from agents.orchestrator import run_daily
            run_daily(dry_run=False)
        except Exception as error:
            events.log("system", f"Scan error: {error}")
        finally:
            events.scan_complete()

    socketio.start_background_task(execute_scan)
    return jsonify({"ok": True, "message": "Scan started. Watch the Office tab for the agents."})


@app.route("/api/portfolio/add", methods=["POST"])
def api_portfolio_add():
    """Append a new holding to memory/portfolio.json after validation."""
    from utils.portfolio_loader import _validate_holding

    raw_input = request.json or {}
    cleaned = _validate_holding(raw_input, index=0)
    if cleaned is None:
        return jsonify({
            "ok": False,
            "error": "Invalid holding. Check ticker (uppercase letters, numbers, dot, dash), shares (non-negative number), and avg_cost_cad (non-negative number).",
        }), 400

    portfolio = _read_json_or_default(PORTFOLIO_PATH, {
        "holdings": [], "cash_available": 0, "currency": "CAD", "account": "Personal",
    })
    portfolio.setdefault("holdings", [])

    # Reject duplicates.
    if any(h.get("ticker", "").upper() == cleaned["ticker"] for h in portfolio["holdings"]):
        return jsonify({"ok": False, "error": f"{cleaned['ticker']} is already in the portfolio."}), 409

    portfolio["holdings"].append(cleaned)
    _write_json(PORTFOLIO_PATH, portfolio)
    return jsonify({"ok": True, "holding": cleaned})


@app.route("/api/portfolio/remove", methods=["POST", "DELETE"])
def api_portfolio_remove():
    """Remove a holding by ticker. Idempotent: returns ok even if absent."""
    if request.method == "DELETE":
        ticker = (request.args.get("ticker") or "").upper().strip()
    else:
        ticker = str((request.json or {}).get("ticker", "")).upper().strip()

    if not ticker:
        return jsonify({"ok": False, "error": "ticker is required"}), 400

    portfolio = _read_json_or_default(PORTFOLIO_PATH, {"holdings": []})
    before = len(portfolio.get("holdings", []))
    portfolio["holdings"] = [
        h for h in portfolio.get("holdings", []) if h.get("ticker", "").upper() != ticker
    ]
    removed = before - len(portfolio["holdings"])
    _write_json(PORTFOLIO_PATH, portfolio)
    return jsonify({"ok": True, "removed": removed})


@app.route("/api/portfolio/prices")
def api_portfolio_prices():
    """Fetch live prices for all holdings and compute unrealised PnL."""
    from utils.data_fetcher import get_fx_rates, get_ohlcv

    portfolio = _read_json_or_default(PORTFOLIO_PATH, {"holdings": []})
    fx_rates = get_fx_rates()
    usd_to_cad = fx_rates.get("USDCAD", 1.38)

    enriched_holdings = []
    for holding in portfolio.get("holdings", []):
        yfinance_ticker = (
            holding["ticker"] + ".TO" if holding.get("exchange") == "TSX" else holding["ticker"]
        )
        try:
            df = get_ohlcv(yfinance_ticker, days=5)
            current_price = float(df["close"].iloc[-1])
        except Exception:
            current_price = None

        price_in_cad = None
        unrealised_pnl_pct = None
        if current_price is not None:
            price_in_cad = (
                current_price * usd_to_cad if holding.get("currency") == "USD" else current_price
            )
            avg_cost = holding.get("avg_cost_cad", 0)
            if avg_cost and avg_cost > 0:
                unrealised_pnl_pct = round(((price_in_cad - avg_cost) / avg_cost) * 100, 2)

        enriched_holdings.append({
            **holding,
            "current_price": current_price,
            "current_price_cad": round(price_in_cad, 2) if price_in_cad else None,
            "pnl_pct": unrealised_pnl_pct,
        })

    return jsonify({**portfolio, "holdings": enriched_holdings, "usd_cad": usd_to_cad})


# WebSocket events ────────────────────────────────────────────────────────────

@socketio.on("trigger_scan")
def handle_trigger_scan(data):
    """Run a scan in the background and stream agent state events to the UI.

    The scan_type is whitelisted and we only call in-process orchestrator
    functions, so this endpoint cannot be used to execute arbitrary code
    even if the socket is exposed on the LAN.
    """
    requested_scan = (data or {}).get("scan_type", "daily")
    if requested_scan not in ALLOWED_SCAN_TYPES:
        emit("log", {"agent_id": "system", "message": f"Refused unknown scan type: {requested_scan}"})
        return

    emit("log", {"agent_id": "system", "message": f"Manual {requested_scan} scan triggered"})

    def execute_scan():
        try:
            # The UI today only supports a manual daily run. Other scan_types
            # are accepted at the socket layer for forward-compatibility but
            # all currently route to run_daily.
            from agents.orchestrator import run_daily
            run_daily(dry_run=False)
        except Exception as error:
            events.log("system", f"Scan error: {error}")
        finally:
            events.scan_complete()

    socketio.start_background_task(execute_scan)


@socketio.on("connect")
def handle_connect():
    emit("log", {"agent_id": "system", "message": "UI connected. All agents idle."})


if __name__ == "__main__":
    host = os.environ.get("REFINERY_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("REFINERY_UI_PORT", "5173"))
    if host != "127.0.0.1":
        logger.warning(
            "UI is binding to %s, which exposes The Refinery on your local network. "
            "Anyone on the same Wi-Fi can read your portfolio.",
            host,
        )
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
