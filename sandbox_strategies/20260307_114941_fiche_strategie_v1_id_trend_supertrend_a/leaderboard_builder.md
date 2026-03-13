# Leaderboard Builder - session 20260307_114941_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=6, multiplier=3.0) - adx(period=22) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 1.25 tp_atr_mult: 4.0 description: ATR trailing stop (1.25x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.690
Best Continuous Score: 50.63

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 50.63 | 0.690 | +55.91% | -45.71% | 1.11 | 116 | continue | approaching_target |
| 2 | 7 | 50.63 | 0.690 | +55.91% | -45.71% | 1.11 | 116 | continue | approaching_target |
| 3 | 8 | 50.63 | 0.690 | +55.91% | -45.71% | 1.11 | 116 | continue | approaching_target |
| 4 | 9 | 50.63 | 0.690 | +55.91% | -45.71% | 1.11 | 116 | continue | approaching_target |
| 5 | 10 | 50.63 | 0.690 | +55.91% | -45.71% | 1.11 | 116 | continue | approaching_target |
| 6 | 3 | 48.34 | 0.586 | +38.35% | -44.75% | 1.09 | 85 | continue | approaching_target |
| 7 | 1 | 45.38 | 0.634 | +46.24% | -47.19% | 1.09 | 98 | continue | low_win_rate |
| 8 | 2 | 45.38 | 0.634 | +46.24% | -47.19% | 1.09 | 98 | continue | low_win_rate |
| 9 | 4 | 45.38 | 0.634 | +46.24% | -47.19% | 1.09 | 98 | continue | low_win_rate |
| 10 | 5 | 45.38 | 0.634 | +46.24% | -47.19% | 1.09 | 98 | continue | low_win_rate |