CANDIDATE_POOLS = {
    "broad_etf":           ["SPY","QQQ","IWM","DIA","UVXY","VTV","SCHD","VGT","VNQ","RSP"],
    "sector_etf":          ["XLE","XLK","XLF","XLV","XLI","XLY","XLU","XLP","XLRE","XLC"],
    "us_large_cap_growth": ["AAPL","MSFT","NVDA","META","AMZN","GOOGL","TSLA","NFLX","ORCL","ADBE"],
    "us_mid_cap_momentum": ["CRWD","DDOG","SNOW","NET","AXON","CELH","GTLB","BILL","RIVN","COIN"],
    "us_financials_rates": ["JPM","GS","MS","BAC","WFC","BRK-B","V","MA","TLT","HYG"],
    "canadian_large_cap":  ["SHOP.TO","RY.TO","TD.TO","BNS.TO","CM.TO","MFC.TO","SLF.TO","BCE.TO","T.TO","CNR.TO"],
    "canadian_energy":     ["CNQ.TO","SU.TO","ENB.TO","TRP.TO","IMO.TO","ABX.TO","WPM.TO","FM.TO","CVE.TO","TXG.TO"],
    "canadian_financials": ["RY.TO","TD.TO","BNS.TO","CM.TO","NA.TO","BMO.TO","MFC.TO","SLF.TO","GWO.TO","IFC.TO"],
    "thematic_speculative":["PLTR","IONQ","RKLB","SMCI","SOUN","ACHR","JOBY","AEHR","ARKG","ARKK"],
    "macro_alternatives":  ["GLD","SLV","USO","TLT","HYG","GDX","BITO","UUP","PDBC","IBIT"],
}

GLOBAL_INDICES = {
    "asian":    ["^N225","^HSI","000001.SS"],
    "european": ["^GDAXI","^FTSE","^FCHI"],
    "us":       ["^GSPC","^IXIC","^DJI","^VIX"],
    "canada":   ["^GSPTSE"],
}

COMMODITIES = ["CL=F","GC=F","SI=F","NG=F"]
FX_PAIRS    = ["CADUSD=X","DX-Y.NYB"]

SCANNER = {
    "min_quality_score": 3,
    "min_rr_ratio": 1.0,
    "min_price_us": 10.0,
    "min_price_ca": 5.0,
    "min_avg_volume": 500_000,
    "earnings_avoid_days": 3,
    "rsi_min": 40,
    "rsi_max": 68,
    "cadusd_move_limit": 0.003,
}

TA = {
    "ema_periods": [9, 20, 50, 200],
    "rsi_period": 14,
    "atr_period": 14,
    "lookback_days": 90,
    "stop_atr_multiplier": 1.5,
}

WATCH_TIER_TRIGGERS = {
    "ema20_cross_lookback_days": 5,
    "volume_ratio_threshold": 2.5,
    "resistance_proximity_pct": 0.005,
    "rsi_cross_level": 50,
    "max_alerts_per_ticker_per_day": 3,
}

ROSTER = {
    "slots_per_category": 10,
    "active_tier_per_category": 4,
    "eviction_health_threshold": 0.35,
    "min_days_before_eviction": 10,
    "regime_breadth_leading": 0.65,
    "regime_breadth_lagging": 0.35,
}

MEMORY = {
    "db_path": "memory/refinery.db",
    "portfolio_file": "memory/portfolio.json",
    "roster_file": "memory/roster.json",
    "strategy_notes": "memory/strategy_notes.md",
    "experiments_file": "memory/strategy_experiments.json",
    "regime_file": "memory/market_regime.json",
    "min_signals_for_patterns": 10,
    "min_signals_for_ratchet": 50,
    "win_rate_alert_threshold": 0.45,
    "postmortem_expiry_days": 5,
}

LEARNING = {
    "ratchet_trial_days": 15,
    "ratchet_improvement_threshold": 0.05,
    "failure_pattern_min_sample": 8,
    "context_max_tokens": 30_000,
}

REPORT = {
    "max_watchlist_items": 8,
    "output_dir": "outputs/",
    "vix_caution_threshold": 20,
    "cadusd_alert_threshold": 0.003,
}

ALERTS = {
    "overnight_move_pct": 0.02,
    "target1_proximity_pct": 0.01,
    "stop_proximity_pct": 0.01,
}

MODELS = {
    "analysis":   "claude-sonnet-4-6",
    "lightweight":"claude-haiku-4-5-20251001",
    "max_tokens_analysis":   2000,
    "max_tokens_lightweight": 500,
}

SCHEDULE = {
    "overnight":   "06:30",
    "daily_brief": "08:15",
    "open_watch":  "09:45",
    "midday":      "12:30",
    "eod":         "16:35",
    "weekly_day":  "monday",
    "weekly_time": "07:30",
    "pulse_interval_minutes": 30,
    "pulse_start": "09:30",
    "pulse_end":   "16:00",
    "timezone":    "America/Toronto",
}
