# Leaderboard Builder - session 20260313_104049_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=18, multiplier=2.5) - adx(period=14) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 25 - short: supertrend.direction == -1 and adx.adx > 25 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 2.5 tp_atr_mult: 5.0 description: ATR trailing stop (2.5x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.603
Best Continuous Score: -64.09

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -64.09 | 0.603 | +182.61% | -90.74% | 1.11 | 263 | continue | ruined |
| 2 | 3 | -64.09 | 0.603 | +182.61% | -90.74% | 1.11 | 263 | continue | ruined |
| 3 | 4 | -64.09 | 0.603 | +182.61% | -90.74% | 1.11 | 263 | continue | ruined |
| 4 | 6 | -64.09 | 0.603 | +182.61% | -90.74% | 1.11 | 263 | stop | ruined |
| 5 | 2 | -100.00 | -20.000 | -276.27% | -100.00% | 0.89 | 907 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -270.23% | -100.00% | 0.78 | 327 | continue | ruined |