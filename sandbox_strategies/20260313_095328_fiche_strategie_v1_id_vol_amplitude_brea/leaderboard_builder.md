# Leaderboard Builder - session 20260313_095328_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=17) - donchian(period=40) - atr(period=14) entry: - long: amplitude_hunter.score > 0.9 and close > donchian.upper - short: amplitude_hunter.score > 0.9 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.1 or cross_any(close, donchian.middle) risk: stop_atr_mult: 3.0 tp_atr_mult: 3.0 description: ATR stop-loss (3.0x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 2 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |
| 3 | 1 | -100.00 | -20.000 | -292.86% | -100.00% | 0.81 | 1124 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -1826.76% | -100.00% | 0.60 | 5081 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -515.38% | -100.00% | 0.79 | 1743 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -292.86% | -100.00% | 0.81 | 1124 | continue | ruined |