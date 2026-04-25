"""Every 30 min during market hours: watch tier quick check. Alert only if triggered."""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from agents.orchestrator import run_pulse
from utils import email_client, notify

def main():
    result = run_pulse()

    triggered = result.get("watch_triggered", [])
    escalated = result.get("escalated_signals", [])
    alerts = result.get("portfolio_alerts", [])

    # Alert on escalated signals
    for s in escalated:
        email_client.send_alert(
            ticker=s["ticker"],
            reason=f"Watch tier escalation: {s.get('setup_type', 'trigger')}",
            key_levels={
                "entry": s.get("entry_low", 0),
                "T1": s.get("target_1", 0),
                "stop": s.get("stop", 0),
            },
        )
        notify.notify(f"Refinery: {s['ticker']}", f"Escalated: {s.get('setup_type', '')}")

    # Alert on portfolio issues
    for a in alerts:
        if a["severity"] in ("warning", "critical"):
            email_client.send_alert(
                ticker=a["ticker"],
                reason=a["message"],
                key_levels={},
            )
            notify.notify(f"Refinery: {a['ticker']}", a["message"][:100])

    if escalated or alerts:
        print(f"Pulse: {len(triggered)} triggers, {len(escalated)} escalated, {len(alerts)} alerts")
    else:
        print(f"Pulse: {len(triggered)} triggers, no alerts")

if __name__ == "__main__":
    main()
