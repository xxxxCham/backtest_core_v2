# Leaderboard Builder - session 20260313_090537_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=10, multiplier=2.5) - adx(period=16) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 1.25 tp_atr_mult: 3.0 description: ATR trailing stop (1.25x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -435.62% | -100.00% | 0.75 | 925 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -201.31% | -100.00% | 0.78 | 502 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -435.62% | -100.00% | 0.75 | 925 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -435.62% | -100.00% | 0.75 | 925 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -309.96% | -100.00% | 0.70 | 523 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -459.16% | -100.00% | 0.77 | 1060 | stop | ruined |