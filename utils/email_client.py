import os
import smtplib
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
TO_EMAIL      = os.getenv("TO_EMAIL", "")

# Alert frequency cap: max 3 alert emails per day
_alert_count = 0
_alert_date = ""


def send(subject: str, body: str, html: bool = False) -> None:
    """Send email. Fails silently, never crashes the run."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = TO_EMAIL
        part = MIMEText(body, "html" if html else "plain")
        msg.attach(part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, TO_EMAIL, msg.as_string())
    except Exception as e:
        logger.error(f"Email send failed: {e}")


def send_brief(brief_html: str, date: str, n_setups: int, pnl_summary: str) -> None:
    subject = f"Refinery Morning Report: {date} | {n_setups} setups | {pnl_summary}"
    send(subject, brief_html, html=True)


def send_alert(ticker: str, reason: str, key_levels: dict) -> None:
    global _alert_count, _alert_date

    today = datetime.now().strftime("%Y-%m-%d")
    if _alert_date != today:
        _alert_date = today
        _alert_count = 0

    if _alert_count >= 3:
        logger.warning(f"Alert suppressed (daily cap reached): {ticker} - {reason}")
        return

    from utils.report_builder import build_alert_html
    body = build_alert_html(ticker, reason, key_levels)
    subject = f"Refinery Alert: {ticker} {reason[:40]}"
    send(subject, body, html=True)
    _alert_count += 1


def send_overnight(text: str, date: str, futures_summary: str) -> None:
    subject = f"Refinery Overnight: {date} | {futures_summary}"
    send(subject, text, html=True)


def send_eod(text: str, date: str, n_tracked: int, overnight_risk: bool) -> None:
    risk_flag = "YES" if overnight_risk else "No"
    subject = f"Refinery EOD: {date} | {n_tracked} signals | Overnight risk: {risk_flag}"
    send(subject, text, html=True)
