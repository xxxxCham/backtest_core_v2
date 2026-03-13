# Leaderboard Builder - session 20260313_112118_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=7, multiplier=3.0) - adx(period=23) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 20 - short: supertrend.direction == -1 and adx.adx > 20 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 2.75 tp_atr_mult: 4.5 description: ATR trailing stop (2.75x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.148
Best Continuous Score: 71.97

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 8 | 71.97 | 1.148 | +31.40% | -38.76% | 1.18 | 64 | accept | target_reached |
| 2 | 5 | 31.00 | 0.583 | +12.78% | -37.63% | 1.04 | 125 | continue | approaching_target |
| 3 | 1 | 24.13 | 0.535 | +10.77% | -39.37% | 1.05 | 89 | continue | approaching_target |
| 4 | 2 | 24.13 | 0.535 | +10.77% | -39.37% | 1.05 | 89 | continue | approaching_target |
| 5 | 3 | 24.13 | 0.535 | +10.77% | -39.37% | 1.05 | 89 | continue | approaching_target |
| 6 | 4 | 24.13 | 0.535 | +10.77% | -39.37% | 1.05 | 89 | continue | approaching_target |
| 7 | 6 | 24.13 | 0.535 | +10.77% | -39.37% | 1.05 | 89 | continue | approaching_target |
| 8 | 7 | 24.13 | 0.535 | +10.77% | -39.37% | 1.05 | 89 | continue | approaching_target |