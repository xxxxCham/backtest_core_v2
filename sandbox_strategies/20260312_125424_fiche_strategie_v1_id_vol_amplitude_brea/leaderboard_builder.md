# Leaderboard Builder - session 20260312_125424_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=41) - donchian(period=10) - atr(period=14) entry: - long: amplitude_hunter.score > 0.7 and close > donchian.upper - short: amplitude_hunter.score > 0.7 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.1 or cross_any(close, donchian.middle) risk: stop_atr_mult: 2.25 tp_atr_mult: 4.0 description: ATR stop-loss (2.25x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -50.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 3 | 1 | -100.00 | -20.000 | -412.76% | -100.00% | 0.72 | 1172 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -1865.53% | -100.00% | 0.56 | 5622 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -742.80% | -100.00% | 0.72 | 2344 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -412.76% | -100.00% | 0.72 | 1172 | stop | ruined |