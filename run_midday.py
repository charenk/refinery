"""12:30 PM EST: Portfolio-only midday check. Alert only if triggered."""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from agents.orchestrator import run_midday
from utils import email_client, notify

def main():
    result = run_midday()

    alerts = result.get("portfolio_alerts", [])
    if alerts:
        for a in alerts:
            if a["severity"] in ("warning", "critical"):
                email_client.send_alert(
                    ticker=a["ticker"],
                    reason=a["message"],
                    key_levels={},
                )
                notify.notify(f"Refinery: {a['ticker']}", a["message"][:100])
        print(f"Midday: {len(alerts)} portfolio alerts")
    else:
        print("Midday: no portfolio alerts")

if __name__ == "__main__":
    main()
