# Leaderboard Builder - session 20260313_083818_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=16, multiplier=3.0) - adx(period=13) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 2.0 tp_atr_mult: 6.0 description: ATR trailing stop (2.0x) and take-profit (6.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -100.00 | -20.000 | +263.54% | -100.00% | 1.12 | 809 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | +263.54% | -100.00% | 1.12 | 809 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | +263.54% | -100.00% | 1.12 | 809 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | +494.80% | -100.00% | 1.30 | 757 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | +263.54% | -100.00% | 1.12 | 809 | stop | ruined |