# The Refinery

Eight agents that watch a personal investment portfolio and email me what changed before the market opens. Lives on a laptop. Costs about ten cents a trading day in API calls.

## What it does

Three things go out by mail or notification:

* A morning report at 8:15 AM ET. What macro did overnight, what the holdings are likely to react to, which watchlist names are setting up.
* Midday and afternoon updates when a holding actually moves.
* macOS notifications when a stock crosses a level the system tracks.

It does not place trades. There is no brokerage integration anywhere in this repo. Market data comes from yfinance. Reasoning runs on Claude. Mail goes out through Gmail.

## Setup

You need a Mac, Python 3.11 or newer, an Anthropic API key, and a Gmail account with a generated App Password.

```
git clone https://github.com/charenk/refinery.git
cd refinery
./setup.sh
```

The installer creates a virtualenv, pulls dependencies, initialises the SQLite store, and (if `.env` is missing) drops into a short wizard that asks for your Anthropic key and Gmail App Password. The Anthropic key is verified with a real one token call before anything is written to disk.

Verify any time with `python check.py`. The dashboard's Portfolio tab has a small form for adding holdings, so you do not need to hand edit JSON.

Then pick how to run it.

* One report now: `python run_daily.py`.
* Schedule on the EST cadence: `python scheduler.py` and leave it running.
* Live dashboard: `cd ui && python app.py`, then visit `http://127.0.0.1:5173`.

## Dashboard

A pixel office in the Severance house style. Eight agents at desks across two cubicle quartets, a Memory kiosk on the right, fluorescent ceiling, green carpet. The office animates from real socket events as scans run, so when the orchestrator dispatches the scanner you actually see a runner walk across the floor.

Five tabs: Office, Morning Report, Portfolio, Roster, Performance.

## Cost

Five to fifteen US cents per trading day in Anthropic charges. Heavy reasoning runs on Sonnet with prompt caching, lighter screens run on Haiku. Knobs live in `config.py` under `MODELS`.

## Safety

Observation only. The dashboard binds to localhost. Set `REFINERY_UI_HOST=0.0.0.0` in `.env` to expose it on your network, and accept that anyone on the same network can read your portfolio if you do.

## License

MIT. See `LICENSE`. See `CLAUDE.md` for the conventions if you want to open a PR.
