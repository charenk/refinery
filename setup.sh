#!/usr/bin/env bash
#
# The Refinery installer.
#
# Default behaviour:
#   1. Verify Python 3.11 or newer is available.
#   2. Create .venv and install pinned dependencies.
#   3. Create memory/portfolio.json from the example template if missing.
#   4. Initialise the SQLite database.
#   5. If .env is missing, drop into an interactive wizard that prompts
#      for ANTHROPIC_API_KEY, SMTP_USER, SMTP_PASSWORD, TO_EMAIL and
#      validates them before writing .env.
#
# Flags:
#   --non-interactive   Skip the wizard. Copies .env.example to .env unchanged.
#                       Use this for CI or scripted installs.
#
# This script is intentionally loud on failure (set -euo pipefail).

set -euo pipefail

NON_INTERACTIVE=0
for arg in "$@"; do
  case "$arg" in
    --non-interactive|--ci)
      NON_INTERACTIVE=1
      ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 1
      ;;
  esac
done

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

mkdir -p memory outputs

if [ ! -f memory/portfolio.json ]; then
  cp memory/portfolio.example.json memory/portfolio.json
  echo "  Created memory/portfolio.json from the example template"
fi

echo "  Initialising memory/refinery.db ..."
python -c "from agents.memory_agent import init_db; init_db()"

# ─── .env handling ───────────────────────────────────────────────────────────

if [ -f .env ]; then
  echo "  .env already exists, leaving it alone"
elif [ "$NON_INTERACTIVE" -eq 1 ] || [ ! -t 0 ]; then
  cp .env.example .env
  echo "  Created .env from .env.example (non-interactive mode)"
else
  echo ""
  echo "─── Configuration wizard ───────────────────────────────────────────"
  echo "Press Ctrl+C at any time to abort. No partial .env will be written."
  echo ""

  # Anthropic API key, with live validation
  ANTHROPIC_KEY=""
  while [ -z "$ANTHROPIC_KEY" ]; do
    echo "Anthropic API key (get one at https://console.anthropic.com/):"
    read -r -p "  ANTHROPIC_API_KEY: " ANTHROPIC_KEY
    if [ -z "$ANTHROPIC_KEY" ]; then
      echo "  Empty value not allowed."
      continue
    fi
    echo "  Pinging Claude with a 1-token request to verify ..."
    if python -c "
from utils.preflight import validate_anthropic_key
import sys
ok, msg = validate_anthropic_key('$ANTHROPIC_KEY')
print('  ' + ('✓ ' if ok else '✗ ') + msg)
sys.exit(0 if ok else 1)
" 2>/dev/null; then
      :
    else
      ANTHROPIC_KEY=""
      echo "  Try again, or Ctrl+C to abort."
    fi
  done
  echo ""

  # Gmail address
  echo "Gmail address that will SEND the reports (use a dedicated account)."
  read -r -p "  SMTP_USER: " SMTP_USER
  echo ""

  # App password (silent)
  echo "Gmail App Password (16 characters, generate at"
  echo "  https://myaccount.google.com/apppasswords)."
  echo "Input is hidden."
  read -r -s -p "  SMTP_PASSWORD: " SMTP_PASSWORD
  echo ""
  echo ""

  # Recipient
  echo "Where to deliver the reports (default: $SMTP_USER)."
  read -r -p "  TO_EMAIL [$SMTP_USER]: " TO_EMAIL
  TO_EMAIL="${TO_EMAIL:-$SMTP_USER}"
  echo ""

  # Optional test email
  echo "Send a one-line test email now to confirm the SMTP setup? [y/N]"
  read -r -p "  send test? " SEND_TEST
  SEND_TEST_LOWER=$(printf '%s' "$SEND_TEST" | tr '[:upper:]' '[:lower:]')
  SEND_TEST_FLAG="False"
  case "$SEND_TEST_LOWER" in
    y|yes) SEND_TEST_FLAG="True" ;;
  esac

  if [ "$SEND_TEST_FLAG" = "True" ]; then
    echo "  Sending test email ..."
    python -c "
from utils.preflight import validate_smtp
ok, msg = validate_smtp('$SMTP_USER', '$SMTP_PASSWORD', '$TO_EMAIL', send_test=True)
print('  ' + ('✓ ' if ok else '✗ ') + msg)
import sys
sys.exit(0 if ok else 1)
" || echo "  (Continuing anyway. Re-check with: python check.py --send-email)"
  fi

  # Write .env atomically (write to temp, then move)
  TMP_ENV=$(mktemp)
  cat > "$TMP_ENV" <<EOF
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
TO_EMAIL=$TO_EMAIL
DEBUG=false
EOF
  mv "$TMP_ENV" .env
  chmod 600 .env
  echo ""
  echo "  Wrote .env (mode 600). Configuration saved."
fi

cat <<'EOF'

Setup complete.

Verify any time with:    python check.py

Next steps:
  1. Edit memory/portfolio.json. Replace the example holding with your own.
     Tickers are uppercase. AAPL, VOO, ENB.TO.

  2. Pick how to run it:
       python run_daily.py --dry-run   one report, no email
       python run_daily.py             one report, real email
       python scheduler.py             daemon on the EST cadence
       cd ui && python app.py          dashboard at http://127.0.0.1:5173

EOF
