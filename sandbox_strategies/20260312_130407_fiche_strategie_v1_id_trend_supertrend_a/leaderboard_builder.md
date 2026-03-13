# Leaderboard Builder - session 20260312_130407_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=18, multiplier=4.0) - adx(period=10) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 35 - short: supertrend.direction == -1 and adx.adx > 35 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 2.25 tp_atr_mult: 3.0 description: ATR trailing stop (2.25x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.535
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 7 | 100.00 | 1.535 | +44.71% | -27.47% | 2.13 | 12 | continue | target_reached |
| 2 | 8 | 80.98 | 1.095 | +37.32% | -37.31% | 1.38 | 22 | accept | target_reached |
| 3 | 3 | 76.69 | 1.104 | +17.68% | -13.67% | 2.84 | 5 | continue | target_reached |
| 4 | 2 | 70.17 | 0.966 | +15.26% | -13.67% | 2.59 | 5 | continue | approaching_target |
| 5 | 6 | -76.15 | 0.177 | -17.80% | -58.57% | 0.84 | 21 | continue | high_drawdown |
| 6 | 1 | -80.73 | 0.297 | -19.01% | -72.20% | 0.89 | 29 | continue | high_drawdown |
| 7 | 4 | -100.00 | -1.191 | -30.78% | -41.44% | 0.30 | 9 | continue | needs_work |
| 8 | 5 | -100.00 | -20.000 | -75.40% | -100.00% | 0.50 | 24 | continue | ruined |