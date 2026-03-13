# Leaderboard Builder - session 20260312_085522_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=47) - donchian(period=50) - atr(period=14) entry: - long: amplitude_hunter.score > 0.6 and close > donchian.upper - short: amplitude_hunter.score > 0.6 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.5 or cross_any(close, donchian.middle) risk: stop_atr_mult: 1.0 tp_atr_mult: 3.5 description: ATR stop-loss (1.0x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 3 | 1 | -100.00 | -20.000 | -215.33% | -100.00% | 0.70 | 648 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -1021.64% | -100.00% | 0.59 | 2843 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -339.20% | -100.00% | 0.74 | 1339 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -173.53% | -100.00% | 0.79 | 807 | continue | ruined |