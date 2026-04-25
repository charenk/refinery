from agents import memory_agent as mem

MAX_TOKENS = 30_000  # approximate — trim if context grows too large


def build_ta_context(ticker: str) -> str:
    """
    Assembles memory context for a TA agent call.
    Returns a formatted string ready to pass as cached_context
    to claude_client.call_with_cached_context().
    """
    parts = []

    tk = mem.get_ticker_knowledge(ticker)
    if tk:
        parts.append(f"## Your knowledge about {ticker}\n")
        if tk.get("ta_notes"):
            parts.append(f"TA notes: {tk['ta_notes']}\n")
        if tk.get("key_levels"):
            parts.append(f"Key levels: {tk['key_levels']}\n")
        if tk.get("earnings_behavior"):
            parts.append(f"Earnings behavior: {tk['earnings_behavior']}\n")
        if tk.get("regime_behavior"):
            parts.append(f"Regime behavior: {tk['regime_behavior']}\n")
        if tk.get("win_rate") and tk.get("signal_count", 0) > 3:
            parts.append(
                f"This system's track record on {ticker}: "
                f"{tk['win_rate']:.0%} win rate over {tk['signal_count']} signals.\n"
            )

    recent = mem.get_recent_signals(ticker=ticker, limit=5)
    if recent:
        parts.append(f"\n## Recent signals for {ticker}\n")
        for s in recent:
            outcome = s.get("outcome", "pending")
            parts.append(
                f"- {s['date']}: {s['setup_type']} quality {s['quality_score']}/5 "
                f"→ {outcome}"
            )
            if s.get("post_mortem"):
                parts.append(f"  Post-mortem: {s['post_mortem'][:200]}")
        parts.append("")

    return "\n".join(parts) if parts else f"No prior knowledge for {ticker} yet."


def build_scanner_context(category: str, regime: str) -> str:
    """Context for scanner evaluating a category."""
    parts = [f"## Current regime: {regime}\n"]

    for setup_type in ["breakout", "pullback", "reversal", "momentum"]:
        condition_key = f"{regime}+{category}"
        pk = mem.get_pattern_knowledge(setup_type, condition_key)
        if pk and pk.get("sample_size", 0) >= 5:
            parts.append(
                f"- {setup_type} in {category} ({regime}): "
                f"{pk['win_rate']:.0%} win rate over {pk['sample_size']} signals"
            )
            if pk.get("common_failures"):
                parts.append(f"  Common failures: {pk['common_failures'][:150]}")

    recent_cat = [s for s in mem.get_recent_signals(limit=30)
                  if s.get("category") == category]
    if recent_cat:
        recent_wins = sum(1 for s in recent_cat if s.get("outcome") in ("hit_t1", "hit_t2"))
        parts.append(
            f"\nRecent {category} signals: {len(recent_cat)} tracked, "
            f"{recent_wins}/{len(recent_cat)} successful"
        )

    return "\n".join(parts)


def build_postmortem_context(trade_id: int) -> str:
    """Full context for post-mortem analysis."""
    with mem.get_conn() as conn:
        trade = conn.execute(
            "SELECT * FROM trades WHERE id=?", (trade_id,)
        ).fetchone()
    if not trade:
        return ""
    trade = dict(trade)

    tk = mem.get_ticker_knowledge(trade["ticker"])
    pk = mem.get_pattern_knowledge(
        trade["setup_type"],
        f"{trade['regime']}+{trade.get('category', 'unknown')}"
    )

    parts = [
        f"## Original signal — {trade['ticker']} on {trade['date']}",
        f"Setup: {trade['setup_type']} | Quality: {trade['quality_score']}/5",
        f"Entry: ${trade['entry_low']}–${trade['entry_high']} | "
        f"T1: ${trade['target_1']} | Stop: ${trade['stop']} | R:R: {trade['rr_ratio']}",
        f"\n## Original reasoning\n{trade.get('reasoning', 'None recorded')}",
        f"\n## Outcome\n{trade['outcome']} at ${trade.get('exit_price', 'N/A')} "
        f"({trade.get('pnl_pct', 0):.1f}%)",
    ]

    if pk and pk.get("sample_size", 0) >= 5:
        parts.append(
            f"\n## Pattern context ({trade['setup_type']} in {trade['regime']})\n"
            f"Historical win rate: {pk['win_rate']:.0%} over {pk['sample_size']} signals\n"
            f"Common failures: {pk.get('common_failures', 'None recorded')}"
        )

    return "\n".join(parts)


def build_sentiment_context(ticker: str) -> str:
    """Context for sentiment agent — ticker knowledge + recent sentiment notes."""
    parts = []
    tk = mem.get_ticker_knowledge(ticker)
    if tk:
        if tk.get("sentiment_notes"):
            parts.append(f"## Previous sentiment notes for {ticker}\n{tk['sentiment_notes']}\n")
        if tk.get("earnings_behavior"):
            parts.append(f"Earnings behavior: {tk['earnings_behavior']}\n")
        if tk.get("sector_correlation"):
            parts.append(f"Sector correlation: {tk['sector_correlation']}\n")
    return "\n".join(parts) if parts else f"No prior sentiment data for {ticker}."


def build_portfolio_context() -> str:
    """Context for portfolio agent: all holdings plus recent signals on held tickers."""
    from utils.portfolio_loader import load_portfolio
    portfolio = load_portfolio()
    parts = ["## Current Portfolio\n"]
    if not portfolio["holdings"]:
        parts.append("No current holdings.\n")
    else:
        for holding in portfolio["holdings"]:
            parts.append(
                f"- {holding['ticker']}: {holding['shares']} shares "
                f"@ ${holding['avg_cost_cad']:.2f} CAD"
            )
            recent_signals = mem.get_recent_signals(ticker=holding["ticker"], limit=3)
            for signal in recent_signals:
                parts.append(
                    f"  Last signal: {signal['date']} {signal['setup_type']} -> {signal['outcome']}"
                )
    parts.append(f"\nCash available: ${portfolio['cash_available']:.2f} {portfolio['currency']}")
    return "\n".join(parts)
