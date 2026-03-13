# Leaderboard Builder - session 20260312_113839_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=13, multiplier=3.5) - adx(period=10) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: ATR trailing stop (2.0x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 3 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 4 | 4 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 5 | 1 | -100.00 | -20.000 | -126.36% | -100.00% | 0.79 | 273 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -270.74% | -100.00% | 0.72 | 407 | stop | ruined |