# Leaderboard Builder - session 20260312_121647_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=8, multiplier=3.0) - adx(period=11) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 1.75 tp_atr_mult: 5.5 description: ATR trailing stop (1.75x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 2 | 1 | -100.00 | -20.000 | -97.67% | -100.00% | 0.96 | 1757 | continue | ruined |
| 3 | 2 | -100.00 | -20.000 | -1251.03% | -100.00% | 0.59 | 3327 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -523.72% | -100.00% | 0.56 | 1492 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -1561.33% | -100.00% | 0.53 | 4367 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -1879.24% | -100.00% | 0.53 | 5425 | continue | ruined |