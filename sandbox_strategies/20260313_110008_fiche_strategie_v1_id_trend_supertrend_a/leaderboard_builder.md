# Leaderboard Builder - session 20260313_110008_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=18, multiplier=3.0) - adx(period=23) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 2.25 tp_atr_mult: 3.0 description: ATR trailing stop (2.25x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.490
Best Continuous Score: 60.13

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 8 | 60.13 | 0.490 | +215.35% | -50.21% | 1.48 | 112 | continue | high_drawdown |
| 2 | 5 | 47.19 | 0.406 | +92.03% | -47.76% | 1.21 | 97 | continue | needs_work |
| 3 | 3 | 43.86 | 0.489 | +191.04% | -53.36% | 1.26 | 147 | continue | high_drawdown |
| 4 | 4 | 43.86 | 0.489 | +191.04% | -53.36% | 1.26 | 147 | continue | high_drawdown |
| 5 | 6 | 43.86 | 0.489 | +191.04% | -53.36% | 1.26 | 147 | continue | high_drawdown |
| 6 | 7 | 43.86 | 0.489 | +191.04% | -53.36% | 1.26 | 147 | continue | high_drawdown |
| 7 | 9 | 43.86 | 0.489 | +191.04% | -53.36% | 1.26 | 147 | continue | high_drawdown |
| 8 | 1 | 34.35 | 0.398 | +34.93% | -49.40% | 1.08 | 83 | continue | needs_work |
| 9 | 10 | 4.36 | 0.242 | +8.73% | -45.76% | 1.03 | 64 | continue | needs_work |
| 10 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |