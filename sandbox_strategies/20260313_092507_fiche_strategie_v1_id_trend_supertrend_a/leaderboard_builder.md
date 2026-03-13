# Leaderboard Builder - session 20260313_092507_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=8, multiplier=2.5) - adx(period=21) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 3.0 tp_atr_mult: 3.5 description: ATR trailing stop (3.0x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.370
Best Continuous Score: -92.96

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -92.96 | 0.179 | -36.50% | -86.82% | 0.91 | 44 | continue | high_drawdown |
| 2 | 5 | -94.74 | 0.099 | -64.17% | -89.82% | 0.88 | 67 | continue | high_drawdown |
| 3 | 2 | -100.00 | -0.278 | -66.66% | -76.96% | 0.69 | 117 | continue | high_drawdown |
| 4 | 3 | -100.00 | 0.370 | -72.20% | -98.00% | 0.89 | 310 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -196.64% | -100.00% | 0.85 | 351 | continue | ruined |
| 6 | 6 | -100.00 | 0.243 | -79.63% | -96.45% | 0.91 | 260 | stop | ruined |