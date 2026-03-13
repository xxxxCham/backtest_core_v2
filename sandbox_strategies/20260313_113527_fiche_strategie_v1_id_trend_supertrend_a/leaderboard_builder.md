# Leaderboard Builder - session 20260313_113527_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=19, multiplier=3.5) - adx(period=11) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 2.5 tp_atr_mult: 4.0 description: ATR trailing stop (2.5x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.371
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | 0.371 | -92.48% | -98.67% | 0.84 | 78 | continue | ruined |
| 2 | 2 | -100.00 | 0.371 | -92.48% | -98.67% | 0.84 | 78 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -49.61% | -100.00% | 0.93 | 126 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -110.94% | -100.00% | 0.78 | 63 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -110.94% | -100.00% | 0.78 | 63 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -110.94% | -100.00% | 0.78 | 63 | stop | ruined |