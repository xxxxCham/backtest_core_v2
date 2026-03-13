# Leaderboard Builder - session 20260313_084123_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=20, multiplier=3.5) - adx(period=12) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 20 - short: supertrend.direction == -1 and adx.adx > 20 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 1.75 tp_atr_mult: 4.0 description: ATR trailing stop (1.75x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.011
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 100.00 | 1.011 | +104.28% | -10.31% | 2.50 | 72 | accept | target_reached |