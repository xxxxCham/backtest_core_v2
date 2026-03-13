# Leaderboard Builder - session 20260312_132117_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=20, multiplier=2.0) - adx(period=22) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 35 - short: supertrend.direction == -1 and adx.adx > 35 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 1.25 tp_atr_mult: 2.5 description: ATR trailing stop (1.25x) and take-profit (2.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -100.00 | -20.000 | -138.58% | -100.00% | 0.00 | 4 | continue | insufficient_trades |
| 3 | 2 | -100.00 | -0.217 | -41.22% | -71.96% | 0.46 | 4 | continue | insufficient_trades |
| 4 | 3 | -100.00 | -20.000 | -185.01% | -100.00% | 0.23 | 19 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -185.01% | -100.00% | 0.23 | 19 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -121.85% | -100.00% | 0.00 | 4 | stop | insufficient_trades |