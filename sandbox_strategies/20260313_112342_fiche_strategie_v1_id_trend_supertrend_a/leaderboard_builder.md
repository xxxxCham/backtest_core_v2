# Leaderboard Builder - session 20260313_112342_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=20, multiplier=3.0) - adx(period=18) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 1.25 tp_atr_mult: 4.5 description: ATR trailing stop (1.25x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.165
Best Continuous Score: -54.43

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | -54.43 | 0.165 | -16.31% | -54.41% | 0.97 | 308 | stop | high_drawdown |
| 2 | 1 | -100.00 | -20.000 | -265.12% | -100.00% | 0.82 | 704 | continue | ruined |
| 3 | 2 | -100.00 | -20.000 | -116.20% | -100.00% | 0.82 | 313 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -424.06% | -100.00% | 0.77 | 837 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -424.06% | -100.00% | 0.77 | 837 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -424.06% | -100.00% | 0.77 | 837 | continue | ruined |