# Leaderboard Builder - session 20260313_103313_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=17, multiplier=3.0) - adx(period=10) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 2.5 tp_atr_mult: 5.0 description: ATR trailing stop (2.5x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.573
Best Continuous Score: 24.66

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 24.66 | 0.573 | +50.25% | -65.48% | 1.05 | 355 | continue | high_drawdown |
| 2 | 9 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |
| 3 | 1 | -100.00 | -20.000 | -260.86% | -100.00% | 0.83 | 409 | continue | ruined |
| 4 | 2 | -100.00 | -20.000 | -260.86% | -100.00% | 0.83 | 409 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -170.22% | -100.00% | 0.87 | 351 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -170.22% | -100.00% | 0.87 | 351 | continue | ruined |
| 7 | 6 | -100.00 | -20.000 | -170.22% | -100.00% | 0.87 | 351 | continue | ruined |
| 8 | 7 | -100.00 | -20.000 | -170.22% | -100.00% | 0.87 | 351 | continue | ruined |
| 9 | 8 | -100.00 | -20.000 | -170.22% | -100.00% | 0.87 | 351 | continue | ruined |