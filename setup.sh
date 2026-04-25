#!/usr/bin/env bash
#
# The Refinery - one-shot installer.
#
# What this does, in order:
#   1. Verify python3 is available.
#   2. Create a .venv in the current directory.
#   3. Install pinned dependencies from requirements.txt.
#   4. Copy .env.example to .env if .env doesn't exist.
#   5. Copy memory/portfolio.example.json to memory/portfolio.json if missing.
#   6. Initialize the SQLite database (creates memory/refinery.db with the
#      full schema; safe to re-run).
#
# This script is intentionally loud on failure (set -euo pipefail).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo "Setting up The Refinery in $REPO_ROOT"

# Pick the best available Python interpreter (>= 3.11 required because Flask 3
# and pandas 2 have dropped support for older versions).
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Error: Python 3.11 or newer is required." >&2
  echo "       Install it from python.org or via Homebrew (brew install python@3.12)." >&2
  exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo "  Using $PYTHON_BIN (Python $PYTHON_VERSION)"

if [ ! -d .venv ]; then
  echo "  Creating virtualenv .venv ..."
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "  Upgrading pip ..."
pip install --quiet --upgrade pip

echo "  Installing dependencies (this can take a minute) ..."
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created .env from .env.example (edit it before running)"
else
  echo "  .env already exists, leaving it alone"
fi

mkdir -p memory outputs
if [ ! -f memory/portfolio.json ]; then
  cp memory/portfolio.example.json memory/portfolio.json
  echo "  Created memory/portfolio.json from the example template"
else
  echo "  memory/portfolio.json already exists, leaving it alone"
fi

echo "  Initializing memory/refinery.db ..."
python -c "from agents.memory_agent import init_db; init_db()"

cat <<'EOF'

Setup complete.

Next steps:
  1. Edit .env
       ANTHROPIC_API_KEY  from https://console.anthropic.com/
       SMTP_USER          your dedicated Gmail address (use an App Password)
       SMTP_PASSWORD      the App Password (not your main Gmail password)
       TO_EMAIL           where reports should land
  2. Edit memory/portfolio.json
       Replace the example holding with your own. Tickers must be uppercase
       (e.g. AAPL, VOO, ENB.TO).
  3. Run the system
       python scheduler.py             scheduler daemon (runs in foreground)
       cd ui && python app.py          dashboard at http://127.0.0.1:5173

Or run a one-off morning report immediately:
       python run_daily.py --dry-run   no email, prints to stdout
       python run_daily.py             real run, sends email

EOF
