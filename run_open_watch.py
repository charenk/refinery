"""9:45 AM EST: Post-open watch tier check. Alert only if triggered."""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from agents.orchestrator import run_open_watch
from utils import email_client, notify

def main():
    result = run_open_watch()

    triggered = result.get("watch_triggered", [])
    if triggered:
        lines = [f"Watch tier triggers ({result['regime']} regime):"]
        for w in triggered:
            lines.append(f"  {w['ticker']} ({w['category']}): {', '.join(w['triggers'])} at ${w['close']:.2f}")
        text = "\n".join(lines)

        for w in triggered[:3]:
            email_client.send_alert(
                ticker=w["ticker"],
                reason=", ".join(w["triggers"]),
                key_levels={"close": w["close"]},
            )
            notify.notify(f"Refinery: {w['ticker']}", ", ".join(w["triggers"]))

        print(text)
    else:
        print("No watch tier triggers.")

if __name__ == "__main__":
    main()
