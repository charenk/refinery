# The Refinery

> A small office of mathematicians who watch your portfolio and tell you what changed.

The Refinery is a local, multi-agent system that monitors a personal
investment account and delivers three things:

1. A **morning report** in your inbox before the market opens.
2. **Event updates** during the day when something actually moves.
3. **Pattern alerts** as macOS notifications when a holding crosses a
   threshold worth your attention.

It does not place trades. It observes and reports. The whole thing runs on
your laptop, costs a few cents a day in API calls, and the source is yours
to read and change.

---

## Quickstart

```bash
git clone https://github.com/charenk/refinery.git
cd refinery
./setup.sh
```

Then edit `.env` (Anthropic API key, Gmail SMTP) and `memory/portfolio.json`
(your holdings), and run:

```bash
python scheduler.py            # background scheduler
cd ui && python app.py         # dashboard at http://127.0.0.1:5173
```

To try it once before scheduling, run a dry-run report:

```bash
python run_daily.py --dry-run  # prints today's brief, sends nothing
python run_daily.py            # real run, emails the brief
```

---

## What you get

### Morning report

A pre-market brief that arrives in your inbox at 8:15 AM ET on weekdays.
It contains:

- The current market regime (trending, choppy, defensive) with the
  evidence behind that call.
- What overnight macro and global indices did, and what that implies for
  the day.
- Each of your holdings with a one-line read on what to watch for today
  (catalyst proximity, level proximity, news flow).
- New setups the system found in the watchlist, with entry zone, target,
  stop, and a reasoning record.

### Event updates

Mid-day and end-of-day updates only when something material changes. Quiet
days stay quiet. When an update fires, the email tells you what triggered
it and what (if anything) you might want to do.

### Pattern alerts

When a stock you own or watch crosses a threshold the system tracks
(volume spike, support break, resistance test, EMA cross), you get a
macOS notification and an email. Maximum three per ticker per day so the
phone never becomes noise.

---

## Architecture

```
                     scheduler.py  (cron-like daemon)
                          |
                          v
                     orchestrator
                       /  |  \
                      /   |   \
                scanner   |   portfolio_agent
                          |
                  +-------+-------+
                  |       |       |
              ta_agent  sentiment_agent
                  |       |       |
                  +-------+-------+
                          |
                          v
                    memory_agent
                          |
                          v
                  memory/refinery.db
                          |
            (post-mortem and learning agents
             run weekly off the same store)

UI:  ui/app.py  serves http://127.0.0.1:5173 with five tabs:
     Office . Morning Report . Portfolio . Roster . Performance
```

Nine agents in [agents/](agents/), shared utilities in [utils/](utils/),
the dashboard in [ui/](ui/), and run entry points at the repo root
([run_daily.py](run_daily.py), [run_overnight.py](run_overnight.py), and
the rest).

---

## Configuration

| File | What it holds |
|---|---|
| [.env](.env.example) | Secrets: Anthropic key, SMTP credentials, recipient email |
| [config.py](config.py) | Behaviour: ticker pools, schedule, thresholds, model tiers |
| [memory/portfolio.json](memory/portfolio.example.json) | Your holdings (uses the example template on first run) |
| [memory/refinery.db](memory/) | SQLite store the agents read and write |

If you want to change *what* the system watches or *when* it runs, edit
`config.py`. If you want to change *how* it reasons, the prompt for each
agent is in `agents/<agent_name>.py:SYSTEM_PROMPT`.

---

## Safety

- **The Refinery does not place trades.** There is no brokerage
  integration anywhere in this repo, and there will not be one. It is
  observation and reporting only.
- **Your portfolio data never leaves your machine** except in the
  prompt sent to Anthropic when an agent reasons about it. If that
  matters to you, audit `utils/claude_client.py` to see exactly what is
  sent.
- **The dashboard binds to 127.0.0.1 by default.** It is not reachable
  from your local network unless you set `REFINERY_UI_HOST=0.0.0.0` in
  the environment. Anyone who can reach the port can read your
  portfolio.

See [CLAUDE.md](CLAUDE.md) for the full set of conventions and security
rules that govern contributions.

---

## Cost

Running the full daily schedule (overnight scan, 8:15 AM brief, mid-day
check, EOD summary, weekly review) costs roughly **5 to 15 US cents per
trading day** in Anthropic API charges, depending on how active your
watchlist is. The scanner and pulse runs use Haiku; the heavier reasoning
(TA, post-mortems, learning) uses Sonnet with prompt caching. Cost
controls are documented in [config.py](config.py) under `MODELS`.

---

## License

[MIT](LICENSE) — fork it, ship your own version, just keep the notice.

## Origin

Extracted from a private project that powered the maintainer's own
portfolio. The agent design and learning loop come from that work; the
public release sanitises the data and reframes the product around a
generic personal investor.
