# Leaderboard Builder - session 20260312_111110_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=11, multiplier=3.0) - adx(period=10) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 2.25 tp_atr_mult: 5.5 description: ATR trailing stop (2.25x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.954
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 100.00 | 1.954 | +85.56% | -42.24% | 1.55 | 51 | continue | target_reached |
| 2 | 7 | 100.00 | 1.954 | +85.56% | -42.24% | 1.55 | 51 | continue | target_reached |
| 3 | 8 | 100.00 | 1.358 | +38.66% | -29.94% | 1.31 | 58 | accept | target_reached |
| 4 | 5 | -82.48 | -0.410 | -21.96% | -50.24% | 0.87 | 27 | continue | high_drawdown |
| 5 | 3 | -97.82 | 0.079 | -44.12% | -71.43% | 0.83 | 52 | continue | high_drawdown |
| 6 | 1 | -100.00 | -0.391 | -60.50% | -81.79% | 0.83 | 74 | continue | high_drawdown |
| 7 | 2 | -100.00 | -0.564 | -44.79% | -67.73% | 0.80 | 64 | continue | high_drawdown |
| 8 | 4 | -100.00 | -2.523 | -72.18% | -80.87% | 0.69 | 60 | continue | high_drawdown |