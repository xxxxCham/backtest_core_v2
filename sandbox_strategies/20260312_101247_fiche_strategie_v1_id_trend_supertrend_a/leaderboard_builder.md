# Leaderboard Builder - session 20260312_101247_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=7, multiplier=3.0) - adx(period=16) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 35 - short: supertrend.direction == -1 and adx.adx > 35 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 2.25 tp_atr_mult: 5.5 description: ATR trailing stop (2.25x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 2 | 3 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 3 | 1 | -100.00 | -20.000 | -2210.27% | -100.00% | 0.52 | 7116 | continue | ruined |
| 4 | 2 | -100.00 | -20.000 | -1940.21% | -100.00% | 0.52 | 6269 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -3459.72% | -100.00% | 0.51 | 11107 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -754.92% | -100.00% | 0.47 | 2296 | continue | ruined |