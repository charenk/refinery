"""4:35 PM EST: End of day review. Always sends EOD summary."""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from agents.orchestrator import run_eod
from utils import email_client, notify, report_builder

def main():
    from utils.preflight import run_or_die
    run_or_die()
    result = run_eod()

    html = report_builder.build_eod_html(result)

    email_client.send_eod(
        text=html,
        date=result["timestamp"][:10],
        n_tracked=result.get("n_tracked", 0),
        overnight_risk=result.get("overnight_risk", False),
    )

    notify.notify("Refinery EOD", f"{len(result.get('resolved_signals', []))} resolved")

    report_builder.save_output(html, "eod")

    print(f"EOD sent: {len(result.get('resolved_signals', []))} resolved, {result['regime']} regime")

if __name__ == "__main__":
    main()
