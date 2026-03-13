# Leaderboard Builder - session 20260312_111856_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=20, multiplier=3.5) - adx(period=19) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 1.5 tp_atr_mult: 4.5 description: ATR trailing stop (1.5x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -481.13% | -100.00% | 0.75 | 1023 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -490.57% | -100.00% | 0.79 | 1375 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -490.57% | -100.00% | 0.79 | 1375 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -242.21% | -100.00% | 0.79 | 696 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -272.06% | -100.00% | 0.72 | 539 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -815.58% | -100.00% | 0.71 | 2039 | stop | ruined |