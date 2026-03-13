# Leaderboard Builder - session 20260312_102058_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=15, multiplier=3.0) - adx(period=15) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 1.25 tp_atr_mult: 3.0 description: ATR trailing stop (1.25x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -0.122
Best Continuous Score: -12.94

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | -12.94 | -0.122 | -1.57% | -6.28% | 0.91 | 43 | continue | needs_work |
| 2 | 6 | -74.05 | -1.110 | -11.02% | -13.64% | 0.41 | 32 | stop | losing_per_trade |
| 3 | 4 | -78.18 | -1.196 | -13.67% | -14.11% | 0.39 | 45 | continue | losing_per_trade |
| 4 | 3 | -91.63 | -1.574 | -19.41% | -19.78% | 0.40 | 73 | continue | losing_per_trade |
| 5 | 1 | -100.00 | -2.674 | -61.84% | -62.55% | 0.43 | 226 | continue | high_drawdown |
| 6 | 2 | -100.00 | -2.162 | -39.98% | -42.31% | 0.41 | 137 | continue | wrong_direction |