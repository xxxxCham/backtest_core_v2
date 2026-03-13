# Leaderboard Builder - session 20260312_081325_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=17, multiplier=2.0) - adx(period=20) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 1.5 tp_atr_mult: 4.5 description: ATR trailing stop (1.5x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 3 | 1 | -100.00 | -20.000 | -132.68% | -100.00% | 0.92 | 723 | continue | ruined |
| 4 | 2 | -100.00 | -20.000 | -385.26% | -100.00% | 0.83 | 1205 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -528.50% | -100.00% | 0.87 | 2073 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -263.76% | -100.00% | 0.80 | 669 | continue | ruined |