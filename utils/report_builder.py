"""
Report builder: generates HTML emails and markdown output files.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared HTML helpers
# ---------------------------------------------------------------------------

_CSS = """\
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 680px; margin: 0 auto; padding: 24px 16px; color: #2d2d2d; background: #faf8f5; line-height: 1.5; }
h1 { color: #1a1a1a; border-bottom: 2px solid #e8a87c; padding-bottom: 10px; font-size: 22px; margin-bottom: 4px; letter-spacing: -0.3px; }
h2 { color: #2d2d2d; font-size: 15px; margin-top: 28px; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.date { color: #888; font-size: 13px; margin-bottom: 16px; }
.market-bar { background: #fff; border: 1px solid #e0dcd5; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.market-bar div { font-size: 13px; color: #555; }
.market-bar strong { color: #1a1a1a; }
.card { background: #fff; border: 1px solid #e0dcd5; border-radius: 8px; padding: 16px; margin: 12px 0; }
.card-header { font-weight: 700; font-size: 16px; color: #1a1a1a; margin-bottom: 8px; }
.ticker { letter-spacing: 0.5px; }
.setup-type { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px; margin-left: 8px; vertical-align: middle; }
.breakout { background: #d4edda; color: #155724; }
.pullback { background: #cce5ff; color: #004085; }
.reversal { background: #f8d7da; color: #721c24; }
.momentum { background: #fff3cd; color: #856404; }
.quality { color: #e8a87c; font-size: 14px; margin-left: 6px; }
.levels-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px; margin: 10px 0; font-size: 13px; }
.level-label { color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; }
.level-value { color: #1a1a1a; font-weight: 600; font-size: 14px; }
.level-value.stop { color: #dc3545; }
.level-value.target { color: #28a745; }
.sentiment { font-size: 13px; margin-top: 10px; padding-top: 10px; border-top: 1px solid #f0ece6; }
.sentiment-pos { color: #28a745; }
.sentiment-neg { color: #dc3545; }
.sentiment-neutral { color: #666; }
.analysis { font-size: 13px; color: #444; margin-top: 8px; line-height: 1.5; }
.alert { background: #fff3cd; border-left: 3px solid #ffc107; padding: 10px 14px; margin: 8px 0; font-size: 13px; border-radius: 0 6px 6px 0; }
.alert-critical { background: #f8d7da; border-left-color: #dc3545; }
.no-setups { text-align: center; padding: 24px; color: #888; font-size: 14px; }
.pnl-pos { color: #28a745; font-weight: 600; }
.pnl-neg { color: #dc3545; font-weight: 600; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px; }
.badge-add { background: #d4edda; color: #155724; }
.badge-remove { background: #f8d7da; color: #721c24; }
.badge-promote { background: #cce5ff; color: #004085; }
.risk-banner { padding: 12px 16px; border-radius: 8px; font-size: 14px; font-weight: 600; margin-bottom: 20px; text-align: center; }
.risk-yes { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
.risk-no { background: #f0ece6; color: #888; border: 1px solid #e0dcd5; }
.footer { margin-top: 28px; padding-top: 14px; border-top: 1px solid #e0dcd5; font-size: 11px; color: #aaa; text-align: center; }
"""


def _vix_color(vix) -> str:
    if vix and vix >= 25:
        return "#dc3545"
    if vix and vix >= 20:
        return "#e8a87c"
    return "#28a745"


def _email_wrapper(title: str, date_str: str, body_sections: str) -> str:
    """Wrap body sections in the shared HTML boilerplate and CSS."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
{_CSS}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="date">{date_str}</div>
{body_sections}
<div class="footer">
    The Refinery | Generated {datetime.now().strftime('%H:%M EST')}<br>
    This is not financial advice. Always do your own research.
</div>
</body></html>"""


def _pnl_span(pnl_pct: float) -> str:
    cls = "pnl-pos" if pnl_pct >= 0 else "pnl-neg"
    return f'<span class="{cls}">{pnl_pct:+.1f}%</span>'


# ---------------------------------------------------------------------------
# Daily Brief
# ---------------------------------------------------------------------------

def build_brief_html(result: dict) -> str:
    """Build HTML email for daily brief."""
    signals = result.get("signals", [])
    regime = result.get("regime", "unknown")
    vix = result.get("vix")
    cadusd = result.get("cadusd")
    portfolio = result.get("portfolio", {})
    sentiment = result.get("sentiment", {})

    date_str = datetime.now().strftime('%A, %B %d, %Y')
    vix_display = f"{vix:.2f}" if vix else "N/A"
    cadusd_display = f"{cadusd:.4f}" if cadusd else "N/A"
    n_signals = len(signals)
    vix_c = _vix_color(vix)

    sections = f"""
<div class="market-bar">
    <div>Regime: <strong>{regime.upper()}</strong></div>
    <div>VIX: <strong style="color:{vix_c}">{vix_display}</strong></div>
    <div>CAD/USD: <strong>{cadusd_display}</strong></div>
    <div>Setups: <strong>{n_signals}</strong></div>
</div>
"""

    # Signals
    if signals:
        sections += "<h2>Today's Setups</h2>\n"
        for s in signals:
            setup = s.get("setup_type", "momentum")
            sent = sentiment.get(s["ticker"], {})
            sent_score = sent.get("score", 0)
            sent_class = "sentiment-pos" if sent_score > 0 else "sentiment-neg" if sent_score < 0 else "sentiment-neutral"
            stars = "\u2605" * s.get("quality_score", 0) + "\u2606" * (5 - s.get("quality_score", 0))
            rr = s.get("rr_ratio", 0)
            rr_color = "#28a745" if rr >= 2.0 else "#e8a87c" if rr >= 1.0 else "#dc3545"

            sections += f"""<div class="card">
    <div class="card-header">
        <span class="ticker">{s['ticker']}</span>
        <span class="setup-type {setup}">{setup.upper()}</span>
        <span class="quality">{stars}</span>
    </div>
    <div class="levels-grid">
        <div><span class="level-label">Entry Zone</span><br><span class="level-value">${s.get('entry_low', 0):.2f} - ${s.get('entry_high', 0):.2f}</span></div>
        <div><span class="level-label">Stop Loss</span><br><span class="level-value stop">${s.get('stop', 0):.2f}</span></div>
        <div><span class="level-label">Target 1</span><br><span class="level-value target">${s.get('target_1', 0):.2f}</span></div>
        <div><span class="level-label">Target 2</span><br><span class="level-value target">${s.get('target_2', 0):.2f}</span></div>
    </div>
    <div style="font-size:13px;color:#555;margin:6px 0;">R:R <strong style="color:{rr_color}">{rr:.1f}</strong></div>
    <div class="sentiment {sent_class}">
        Sentiment: {sent_score:+d}/5
        {(' - ' + sent.get('summary', '')[:150]) if sent.get('summary') else ''}
    </div>
    <div class="analysis">
        {s.get('analysis_summary', s.get('reasoning', ''))[:300]}
    </div>
</div>\n"""
    else:
        sections += '<div class="no-setups">No setups meeting quality threshold today. Stay patient.</div>\n'

    # Watch tier triggers
    watch = result.get("watch_triggered", [])
    if watch:
        sections += "<h2>Watch Tier Triggers</h2>\n"
        for w in watch[:5]:
            sections += f'<div class="alert">{w["ticker"]} ({w["category"]}): {", ".join(w["triggers"])} at ${w["close"]:.2f}</div>\n'

    # Portfolio
    port_summary = portfolio.get("summary", "")
    if port_summary and port_summary != "No holdings":
        sections += f"<h2>Portfolio</h2>\n<p style='font-size:13px;'>{port_summary[:500]}</p>\n"

    # Portfolio alerts
    port_alerts = result.get("portfolio_alerts", [])
    if port_alerts:
        for a in port_alerts:
            alert_class = "alert-critical" if a["severity"] == "critical" else "alert"
            sections += f'<div class="alert {alert_class}">{a["message"]}</div>\n'

    return _email_wrapper("Refinery Morning Report", date_str, sections)


def build_brief_markdown(result: dict) -> str:
    """Build markdown output for archiving."""
    signals = result.get("signals", [])
    regime = result.get("regime", "unknown")
    vix = result.get("vix")
    date = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# Refinery Morning Report - {date}",
        f"Regime: {regime} | VIX: {vix or 'N/A'} | Setups: {len(signals)}",
        "",
    ]

    if signals:
        lines.append("## Setups")
        for s in signals:
            lines.append(f"### {s['ticker']} - {s.get('setup_type', '').upper()} (Q{s.get('quality_score', '?')}/5)")
            lines.append(f"- Entry: ${s.get('entry_low', 0):.2f} - ${s.get('entry_high', 0):.2f}")
            lines.append(f"- T1: ${s.get('target_1', 0):.2f} | T2: ${s.get('target_2', 0):.2f}")
            lines.append(f"- Stop: ${s.get('stop', 0):.2f} | R:R: {s.get('rr_ratio', 0):.1f}")
            if s.get("analysis_summary"):
                lines.append(f"- {s['analysis_summary'][:300]}")
            lines.append("")

    watch = result.get("watch_triggered", [])
    if watch:
        lines.append("## Watch Tier Triggers")
        for w in watch:
            lines.append(f"- {w['ticker']} ({w['category']}): {', '.join(w['triggers'])}")
        lines.append("")

    return "\n".join(lines)


def build_overnight_html(result: dict) -> str:
    """Build HTML email for overnight/pre-market check."""
    candidates = result.get("candidates", [])
    alerts = result.get("portfolio_alerts", [])
    regime = result.get("regime", "unknown")
    vix = result.get("vix")
    resolved = result.get("resolved_signals", [])
    vix_display = f"{vix:.2f}" if vix else "N/A"
    date_str = datetime.now().strftime('%A, %B %d, %Y')

    sections = f"""
<div class="market-bar">
    <div>Regime: <strong>{regime.upper()}</strong></div>
    <div>VIX: <strong style="color:{_vix_color(vix)}">{vix_display}</strong></div>
</div>
"""

    # Scan candidates
    if candidates:
        sections += f"<h2>Scan Candidates ({len(candidates)})</h2>\n"
        for c in candidates[:8]:
            setup = c.get("setup_type", "momentum")
            stars = "\u2605" * c.get("quality_score", 0) + "\u2606" * (5 - c.get("quality_score", 0))
            rr = c.get("rr_ratio", 0)
            sections += f"""<div class="card">
    <div class="card-header">
        <span class="ticker">{c['ticker']}</span>
        <span class="setup-type {setup}">{setup.upper()}</span>
        <span class="quality">{stars}</span>
    </div>
    <div style="font-size:13px;color:#555;">R:R <strong>{rr:.1f}</strong></div>
</div>\n"""
    else:
        sections += '<div class="no-setups">No scan candidates this morning.</div>\n'

    # Portfolio alerts
    if alerts:
        sections += "<h2>Portfolio Alerts</h2>\n"
        for a in alerts:
            cls = "alert alert-critical" if a["severity"] == "critical" else "alert"
            sections += f'<div class="{cls}">[{a["severity"].upper()}] {a["message"]}</div>\n'

    # Resolved signals
    if resolved:
        sections += f"<h2>Resolved Signals ({len(resolved)})</h2>\n"
        for r in resolved:
            pnl = r.get("pnl_pct", 0)
            sections += f"""<div class="card">
    <div class="card-header"><span class="ticker">{r['ticker']}</span></div>
    <div style="font-size:13px;">{r['outcome']} | {_pnl_span(pnl)}</div>
</div>\n"""

    return _email_wrapper("Refinery Pre-Market", date_str, sections)


def build_eod_html(result: dict) -> str:
    """Build HTML email for end-of-day summary."""
    resolved = result.get("resolved_signals", [])
    alerts = result.get("portfolio_alerts", [])
    regime = result.get("regime", "unknown")
    vix = result.get("vix")
    vix_display = f"{vix:.2f}" if vix else "N/A"
    n_tracked = result.get("n_tracked", 0)
    overnight_risk = result.get("overnight_risk", False)
    date_str = datetime.now().strftime('%A, %B %d, %Y')

    risk_cls = "risk-yes" if overnight_risk else "risk-no"
    risk_label = "OVERNIGHT RISK: YES" if overnight_risk else "Overnight Risk: No"

    sections = f"""
<div class="market-bar">
    <div>Regime: <strong>{regime.upper()}</strong></div>
    <div>VIX: <strong style="color:{_vix_color(vix)}">{vix_display}</strong></div>
    <div>Tracked: <strong>{n_tracked}</strong></div>
</div>
<div class="risk-banner {risk_cls}">{risk_label}</div>
"""

    # Resolved today
    if resolved:
        sections += f"<h2>Resolved Today ({len(resolved)})</h2>\n"
        for r in resolved:
            pnl = r.get("pnl_pct", 0)
            sections += f"""<div class="card">
    <div class="card-header"><span class="ticker">{r['ticker']}</span></div>
    <div style="font-size:13px;">{r['outcome']} | {_pnl_span(pnl)}</div>
</div>\n"""

    # Alerts
    if alerts:
        sections += "<h2>Alerts</h2>\n"
        for a in alerts:
            cls = "alert alert-critical" if a["severity"] == "critical" else "alert"
            sections += f'<div class="{cls}">[{a["severity"].upper()}] {a["message"]}</div>\n'

    return _email_wrapper("Refinery End of Day", date_str, sections)


def build_alert_html(ticker: str, reason: str, key_levels: dict) -> str:
    """Build compact HTML email for a single alert."""
    is_critical = any(w in reason.lower() for w in ("stop", "critical", "breach", "risk"))
    border_color = "#dc3545" if is_critical else "#e8a87c"

    levels_html = ""
    if key_levels:
        levels_html = '<div class="levels-grid" style="margin-top:12px;">'
        label_map = {"entry": "Entry", "T1": "Target 1", "stop": "Stop", "close": "Close"}
        for k, v in key_levels.items():
            label = label_map.get(k, k.upper())
            val_cls = "level-value stop" if k == "stop" else "level-value target" if k == "T1" else "level-value"
            levels_html += f'<div><span class="level-label">{label}</span><br><span class="{val_cls}">${v:.2f}</span></div>'
        levels_html += "</div>"

    body = f"""
<div class="card" style="border-left: 4px solid {border_color};">
    <div class="card-header"><span class="ticker">{ticker}</span></div>
    <div style="font-size:14px;color:#2d2d2d;margin-top:4px;">{reason}</div>
    {levels_html}
</div>
"""

    return _email_wrapper(f"Refinery Alert: {ticker}", datetime.now().strftime('%A, %B %d, %Y'), body)


def build_weekly_html(result: dict) -> str:
    """Build HTML email for weekly review."""
    regime = result.get("regime", "unknown")
    vix = result.get("vix")
    vix_display = f"{vix:.2f}" if vix else "N/A"
    candidates = result.get("candidates", [])
    review = result.get("learning_review", {})
    proposals = result.get("roster_proposals", [])
    date_str = datetime.now().strftime('%A, %B %d, %Y')

    # Stats bar
    stats = review.get("weekly_stats", {})
    overall = review.get("overall_stats", {})
    w_resolved = stats.get("resolved", 0)
    w_wr = stats.get("win_rate", 0)
    o_resolved = overall.get("resolved", 0)
    o_wr = overall.get("win_rate", 0)

    sections = f"""
<div class="market-bar">
    <div>Regime: <strong>{regime.upper()}</strong></div>
    <div>VIX: <strong style="color:{_vix_color(vix)}">{vix_display}</strong></div>
</div>
<div class="market-bar">
    <div>Week Resolved: <strong>{w_resolved}</strong></div>
    <div>Week Win Rate: <strong>{w_wr:.0%}</strong></div>
    <div>30d Resolved: <strong>{o_resolved}</strong></div>
    <div>30d Win Rate: <strong>{o_wr:.0%}</strong></div>
</div>
"""

    # Top candidates
    if candidates:
        sections += f"<h2>Top Candidates ({len(candidates)})</h2>\n"
        for c in candidates[:10]:
            setup = c.get("setup_type", "momentum")
            stars = "\u2605" * c.get("quality_score", 0) + "\u2606" * (5 - c.get("quality_score", 0))
            rr = c.get("rr_ratio", 0)
            sections += f"""<div class="card">
    <div class="card-header">
        <span class="ticker">{c['ticker']}</span>
        <span class="setup-type {setup}">{setup.upper()}</span>
        <span class="quality">{stars}</span>
    </div>
    <div style="font-size:13px;color:#555;">R:R <strong>{rr:.1f}</strong></div>
</div>\n"""

    # Roster proposals
    if proposals:
        sections += "<h2>Roster Proposals</h2>\n"
        for p in proposals:
            action = p["action"].upper()
            badge_cls = {"ADD": "badge-add", "REMOVE": "badge-remove", "PROMOTE": "badge-promote"}.get(action, "badge-add")
            sections += f"""<div class="card">
    <span class="badge {badge_cls}">{action}</span>
    <strong style="margin-left:8px;">{p['ticker']}</strong> in {p['category']}
    <div style="font-size:13px;color:#555;margin-top:4px;">{p['reason']}</div>
</div>\n"""

    # Learning insights
    claude_analysis = review.get("claude_analysis", "")
    if claude_analysis:
        sections += "<h2>Learning Insights</h2>\n"
        sections += f'<div class="card"><div class="analysis">{claude_analysis[:1000]}</div></div>\n'

    return _email_wrapper("Refinery Weekly Review", date_str, sections)


def save_output(content: str, suffix: str = "brief") -> str:
    """Save output to the outputs directory. Returns file path."""
    from config import REPORT
    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = f"{REPORT['output_dir']}{date_str}_{suffix}.md"
    try:
        with open(filepath, "w") as f:
            f.write(content)
        return filepath
    except Exception as e:
        logger.error(f"Failed to save output: {e}")
        return ""
