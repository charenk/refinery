"""Monday 7:30 AM EST: Weekly review. Always sends weekly summary."""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from agents.orchestrator import run_weekly
from utils import email_client, notify, report_builder

def main():
    from utils.preflight import run_or_die
    run_or_die()
    result = run_weekly()

    html = report_builder.build_weekly_html(result)

    # Send as email
    email_client.send(
        subject=f"Refinery Weekly - {result['timestamp'][:10]} | {result['regime']}",
        body=html,
        html=True,
    )

    notify.notify("Refinery Weekly", f"Review complete | {result['regime']}")

    report_builder.save_output(html, "weekly")

    print(f"Weekly sent: {result['regime']} regime")

if __name__ == "__main__":
    main()
