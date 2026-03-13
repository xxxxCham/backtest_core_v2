# Leaderboard Builder - session 20260312_113305_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=15, multiplier=2.0) - adx(period=18) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 35 - short: supertrend.direction == -1 and adx.adx > 35 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 2.25 tp_atr_mult: 5.0 description: ATR trailing stop (2.25x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.774
Best Continuous Score: 77.99

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 77.99 | 0.774 | +119.85% | -39.44% | 2.00 | 11 | continue | approaching_target |
| 2 | 2 | 63.30 | 0.693 | +91.50% | -48.52% | 1.84 | 10 | continue | approaching_target |
| 3 | 4 | 61.21 | 0.685 | +91.53% | -49.75% | 1.84 | 10 | continue | approaching_target |
| 4 | 1 | 60.99 | 0.695 | +92.45% | -50.09% | 1.86 | 10 | continue | high_drawdown |
| 5 | 9 | 27.87 | 0.493 | +41.06% | -55.00% | 1.15 | 20 | continue | high_drawdown |
| 6 | 8 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 7 | 10 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 8 | 7 | -95.80 | -0.167 | -22.45% | -45.98% | 0.64 | 5 | continue | needs_work |
| 9 | 5 | -100.00 | 0.379 | -29.12% | -88.10% | 0.84 | 13 | continue | high_drawdown |
| 10 | 6 | -100.00 | -0.394 | -38.00% | -56.81% | 0.52 | 6 | continue | high_drawdown |