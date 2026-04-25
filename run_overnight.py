"""6:30 AM EST: Lightweight pre-market check. Always sends email."""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from agents.orchestrator import run_overnight
from utils import email_client, notify, report_builder

def main():
    result = run_overnight()

    html = report_builder.build_overnight_html(result)

    # Futures summary for email subject
    futures_summary = f"Regime: {result['regime']}"
    if result.get("vix"):
        futures_summary += f" | VIX: {result['vix']}"

    email_client.send_overnight(
        text=html,
        date=result["timestamp"][:10],
        futures_summary=futures_summary,
    )

    notify.notify("Refinery Overnight", f"{len(result.get('candidates', []))} candidates, {result['regime']} regime")

    # Save output
    report_builder.save_output(html, "overnight")

    print(f"Overnight sent: {len(result.get('candidates', []))} candidates, {result['regime']} regime")

if __name__ == "__main__":
    main()
