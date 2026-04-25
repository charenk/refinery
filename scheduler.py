"""
Persistent scheduler: runs all Refinery scripts on their EST cadence.

Uses the `schedule` library. Runs as a background process.
All times are in America/Toronto (EST/EDT).
"""

import logging
import subprocess
import sys
import time
from datetime import datetime

import pytz
import schedule

logging.basicConfig(level=logging.INFO, format="%(asctime)s scheduler %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TZ = pytz.timezone("America/Toronto")
PYTHON = sys.executable  # use the same Python that launched scheduler


def _run_script(name: str) -> None:
    """Run a script as a subprocess. Never crashes the scheduler."""
    logger.info(f"Running {name}")
    try:
        result = subprocess.run(
            [PYTHON, name],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            logger.error(f"{name} failed (exit {result.returncode}): {result.stderr[:500]}")
        else:
            logger.info(f"{name} completed: {result.stdout[:200]}")
    except subprocess.TimeoutExpired:
        logger.error(f"{name} timed out after 10 minutes")
    except Exception as e:
        logger.error(f"{name} error: {e}")


def _is_market_hours() -> bool:
    """Check if current time is during market hours (9:30-16:00 ET, weekdays)."""
    now = datetime.now(TZ)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    market_open = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    return market_open <= now <= market_close


def _run_pulse_if_market() -> None:
    """Only run pulse during market hours."""
    if _is_market_hours():
        _run_script("run_pulse.py")


def _run_if_weekday(name: str) -> None:
    """Only run on weekdays."""
    now = datetime.now(TZ)
    if now.weekday() < 5:
        _run_script(name)


def main():
    from config import SCHEDULE

    logger.info("Refinery Scheduler starting")
    logger.info(f"Timezone: {SCHEDULE['timezone']}")
    logger.info(f"Python: {PYTHON}")

    # Daily scripts (weekdays only)
    schedule.every().day.at(SCHEDULE["overnight"]).do(_run_if_weekday, "run_overnight.py")
    schedule.every().day.at(SCHEDULE["daily_brief"]).do(_run_if_weekday, "run_daily.py")
    schedule.every().day.at("09:45").do(_run_if_weekday, "run_open_watch.py")
    schedule.every().day.at(SCHEDULE["midday"]).do(_run_if_weekday, "run_midday.py")
    schedule.every().day.at(SCHEDULE["eod"]).do(_run_if_weekday, "run_eod.py")

    # Pulse every 30 minutes (market hours only)
    schedule.every(SCHEDULE["pulse_interval_minutes"]).minutes.do(_run_pulse_if_market)

    # Weekly review (Monday only)
    schedule.every().monday.at(SCHEDULE["weekly_time"]).do(_run_script, "run_weekly.py")

    logger.info("Schedule configured:")
    for job in schedule.get_jobs():
        logger.info(f"  {job}")

    logger.info("Scheduler running. Press Ctrl+C to stop.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped")

if __name__ == "__main__":
    main()
