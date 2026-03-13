# Leaderboard Builder - session 20260312_120223_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=17, multiplier=4.0) - adx(period=13) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 2.0 tp_atr_mult: 2.0 description: ATR trailing stop (2.0x) and take-profit (2.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 4 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 3 | 1 | -100.00 | -20.000 | -393.89% | -100.00% | 0.08 | 1335 | continue | ruined |
| 4 | 2 | -100.00 | -20.000 | -139.92% | -100.00% | 0.14 | 567 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -413.69% | -100.00% | 0.07 | 1408 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -255.99% | -100.00% | 0.07 | 861 | stop | ruined |