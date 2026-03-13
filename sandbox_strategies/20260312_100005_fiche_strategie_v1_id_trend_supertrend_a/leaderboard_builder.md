# Leaderboard Builder - session 20260312_100005_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=5, multiplier=3.0) - adx(period=12) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 1.75 tp_atr_mult: 5.0 description: ATR trailing stop (1.75x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.966
Best Continuous Score: 70.50

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 8 | 70.50 | 0.966 | +24.40% | -24.43% | 1.16 | 69 | continue | approaching_target |
| 2 | 2 | 57.04 | 0.955 | +23.33% | -31.97% | 1.18 | 42 | continue | low_win_rate |
| 3 | 10 | 50.75 | 0.782 | +16.10% | -28.22% | 1.11 | 62 | continue | approaching_target |
| 4 | 5 | 50.13 | 0.834 | +16.82% | -30.88% | 1.11 | 68 | continue | approaching_target |
| 5 | 9 | 29.42 | 0.588 | +7.26% | -27.78% | 1.05 | 58 | continue | low_win_rate |
| 6 | 3 | 24.78 | 0.893 | +19.71% | -53.32% | 1.14 | 56 | continue | high_drawdown |
| 7 | 6 | 16.33 | 0.536 | +4.68% | -34.24% | 1.04 | 36 | continue | low_win_rate |
| 8 | 1 | -10.49 | 0.600 | +3.59% | -54.77% | 1.02 | 51 | continue | high_drawdown |
| 9 | 4 | -24.34 | 0.788 | +2.61% | -78.00% | 1.01 | 81 | continue | high_drawdown |
| 10 | 7 | -100.00 | -0.459 | -41.10% | -58.49% | 0.80 | 72 | continue | high_drawdown |