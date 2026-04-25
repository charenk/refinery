# The Refinery — Project Instructions

These instructions govern how Claude (and humans) should work in this
repository. They are deliberately short. If a rule conflicts with what you
think is best, raise it in a PR rather than silently breaking the rule.

---

## What this is

The Refinery is a small office of specialised AI agents that watches a
personal investment portfolio and tells the owner what changed. It runs
locally on a Mac, costs a few cents a day in API calls, and delivers three
things:

1. **Morning report.** What happened overnight in macro, indices, FX, and on
   the holdings. Sent to the owner's inbox before market open.
2. **Event updates.** Mid-day and end-of-day summaries when something
   actually moved.
3. **Pattern alerts.** macOS notifications and emails when a stock in the
   portfolio or watchlist crosses a threshold the system cares about.

It does not place trades. It observes and reports.

---

## Quickstart

```bash
git clone https://github.com/charenk/refinery.git
cd refinery
./setup.sh
# Edit .env and memory/portfolio.json, then:
python scheduler.py                # background daemon
cd ui && python app.py             # dashboard at http://127.0.0.1:5173
```

---

## Architecture in ten lines

- **9 agents** in `agents/`: scanner, ta_agent, sentiment_agent,
  portfolio_agent, postmortem_agent, learning_agent, roster_agent,
  orchestrator, memory_agent.
- The orchestrator coordinates the others. Memory_agent is the only module
  that talks to SQLite.
- **Memory** lives in `memory/refinery.db` (SQLite) plus a few JSON files for
  user-editable state (`portfolio.json`, `roster.json`).
- **Run scripts** at the repo root (`run_*.py`) are entry points that the
  scheduler calls on a cron-like cadence (overnight, 8:15 AM, every 30 min
  during market hours, EOD, weekly).
- **UI** is a Flask + Socket.IO server in `ui/` that serves a five-tab
  dashboard. Agents emit Socket.IO events as they run so the office
  animates live.

Full ticker lists, model-tier mapping, and schedule live in `config.py`.

---

## Code conventions

Read these before writing code in this repo.

### Naming

- Public functions, classes, and module-level constants use full words:
  `load_portfolio()`, not `load_pf()`. `AGENTS`, not `AG`.
- Local variables in tight loops can be short, but never single-letter for
  domain concepts (`ticker`, not `t`; `signal`, not `s`).
- Module-level private state is prefixed with one underscore (`_socketio`).
- File names are lowercase with underscores (`portfolio_loader.py`), never
  camelCase.

### Module boundaries

- All SQLite access goes through `agents/memory_agent.py`. No other file
  imports `sqlite3`.
- All Anthropic API calls go through `utils/claude_client.py`. No other file
  imports `anthropic`.
- All emails go through `utils/email_client.py`.
- All macOS notifications go through `utils/notify.py`.
- All `portfolio.json` reads go through `utils/portfolio_loader.py`.

### Configuration

- Thresholds, model names, ticker lists, schedules, and file paths live in
  `config.py`. Never hardcode them inside an agent or run script.
- Secrets (API keys, SMTP passwords) live in `.env`. Never commit `.env`.
  `.env.example` is the canonical list of required variables.

### Agent output contract

Every agent returns both an analysis dict and a string `reasoning_record`
that explains *why*. The reasoning record is what the post-mortem agent
audits later. No agent output ships without one.

### Logging

- Use `logging`, not `print`, in any module that is not a CLI entry point.
- The CLI scripts (`run_*.py`, `roster.py`, `scheduler.py`) may print.
- Failed external calls (Anthropic, yfinance, SMTP, osascript) log a
  warning and return a sentinel. They never crash the scan.

---

## Security rules

The Refinery runs on a personal machine and reads/writes a personal
portfolio. Treat these as inviolable.

1. **Secrets only in `.env`.** Never paste an API key or password into
   source. Never log a full secret. The `.env` file is gitignored.
2. **Validate user-edited JSON on every read.** `portfolio.json` and
   `roster.json` are user-editable. `utils/portfolio_loader.py` shows the
   pattern: regex the ticker, type-check numeric fields, drop bad entries
   with a warning instead of crashing.
3. **Subprocess calls use list-form args.** Never `shell=True`. If a string
   from user input or a socket payload reaches a subprocess, it must be
   whitelisted (`ui/app.py:ALLOWED_SCAN_TYPES` is the example).
4. **AppleScript inputs are escaped.** `utils/notify.py` escapes
   backslashes and double quotes before building the osascript command.
   Don't bypass the helper.
5. **The UI server binds to 127.0.0.1 by default.** Opt-in to LAN exposure
   via the `REFINERY_UI_HOST` environment variable. Anyone on the same
   Wi-Fi who can reach the port can read the portfolio and trigger scans.
6. **No `eval`, `exec`, `pickle.loads`, or `yaml.load` without
   `SafeLoader`.** If you think you need one, raise it; you almost
   certainly don't.
7. **Path traversal protection on user-supplied filenames.** See
   `ui/app.py:api_brief_by_name` for the pattern.

---

## What NOT to add (guardrails against scope creep)

- **No order execution.** The Refinery observes and reports. It will never
  place a trade or interact with a brokerage API. This is a non-negotiable
  product principle, not a TODO.
- **No new model providers in v0.1.x.** Anthropic Claude only. Adding
  OpenAI/Gemini routing introduces config sprawl and obscures the prompt-
  caching strategy that keeps cost in single-digit cents per scan.
- **No social or shared dashboards.** Single-user, local-only.
- **No background telemetry.** The system never phones home. The only
  outbound traffic is to: Anthropic API, yfinance, FRED, RSS feeds, and the
  user's own SMTP server.

---

## Working in this repo

- Branch off `main`, open a PR, get a review (even if the only reviewer is
  you running `/ultrareview`).
- Run `pytest tests/` before pushing.
- If you change an agent's public function signature, update its caller in
  `agents/orchestrator.py` in the same commit.
- If you change the database schema, write a migration in
  `agents/memory_agent.py:init_db()` (additive only; never drop columns).
- Cost-sensitive code (anything that touches `claude_client`) should
  document which model tier it uses and why.

---

## Origin

The Refinery was extracted from a private prior project that powered the
maintainer's own portfolio. That project remains private and is not part
of this release. The agent design, prompt structure, and learning ratchet
all come from that work; the public release sanitises personal data and
re-frames the product around a generic personal investor.
