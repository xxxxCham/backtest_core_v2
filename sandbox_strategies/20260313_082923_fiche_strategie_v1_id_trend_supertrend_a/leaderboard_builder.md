# Leaderboard Builder - session 20260313_082923_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=19, multiplier=3.0) - adx(period=12) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 2.25 tp_atr_mult: 5.0 description: ATR trailing stop (2.25x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.979
Best Continuous Score: 86.53

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 7 | 86.53 | 0.979 | +203.47% | -29.27% | 1.20 | 220 | continue | approaching_target |
| 2 | 8 | 86.53 | 0.979 | +203.47% | -29.27% | 1.20 | 220 | continue | approaching_target |
| 3 | 9 | 86.53 | 0.979 | +203.47% | -29.27% | 1.20 | 220 | continue | approaching_target |
| 4 | 10 | 86.53 | 0.979 | +203.47% | -29.27% | 1.20 | 220 | continue | approaching_target |
| 5 | 1 | 31.08 | 0.617 | +82.84% | -57.20% | 1.08 | 160 | continue | high_drawdown |
| 6 | 2 | 31.08 | 0.617 | +82.84% | -57.20% | 1.08 | 160 | continue | high_drawdown |
| 7 | 5 | 30.06 | 0.563 | +69.83% | -56.50% | 1.07 | 153 | continue | high_drawdown |
| 8 | 6 | 30.06 | 0.563 | +69.83% | -56.50% | 1.07 | 153 | continue | high_drawdown |
| 9 | 3 | -100.00 | -20.000 | -209.00% | -100.00% | 0.78 | 169 | continue | ruined |
| 10 | 4 | -100.00 | -20.000 | -440.10% | -100.00% | 0.79 | 1551 | continue | ruined |