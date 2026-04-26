"""8:15 AM EST: Primary brief generation. Always sends HTML email."""

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from agents.orchestrator import run_daily
from utils import claude_client, email_client, notify, report_builder

def main():
    parser = argparse.ArgumentParser(description="Refinery morning report")
    parser.add_argument("--dry-run", action="store_true", help="Generate brief without saving signals or sending email")
    parser.add_argument("--mock", action="store_true", help="Use mock Claude responses (no API key needed)")
    parser.add_argument("--ticker", type=str, help="Analyze a single ticker instead of full scan")
    args = parser.parse_args()

    from utils.preflight import run_or_die
    run_or_die(
        require_anthropic=not args.mock,
        require_smtp=not args.dry_run,
    )

    if args.mock:
        claude_client.set_mock_mode(True)
        print("[MOCK MODE] Using simulated Claude responses, no API calls will be made.")

    result = run_daily(dry_run=args.dry_run, ticker=args.ticker)

    # Build outputs
    html = report_builder.build_brief_html(result)
    markdown = report_builder.build_brief_markdown(result)

    signals = result.get("signals", [])
    n_setups = len(signals)

    # P&L summary from resolved signals
    pnl_summary = f"{result['regime']} regime"

    if args.dry_run:
        print("[DRY RUN] Brief generated but not saved or emailed.\n")
        print(markdown)
    else:
        # Send email
        email_client.send_brief(
            brief_html=html,
            date=result["timestamp"][:10],
            n_setups=n_setups,
            pnl_summary=pnl_summary,
        )

        # Save outputs
        report_builder.save_output(markdown, "brief")
        report_builder.save_output(html, "brief_html")

        notify.notify("Refinery Morning Report", f"{n_setups} setups | {result['regime']}")

        print(f"Brief sent: {n_setups} setups, {result['regime']} regime")

if __name__ == "__main__":
    main()
