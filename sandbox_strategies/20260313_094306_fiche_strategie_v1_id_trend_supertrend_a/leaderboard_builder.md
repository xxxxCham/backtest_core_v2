# Leaderboard Builder - session 20260313_094306_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=20, multiplier=2.5) - adx(period=16) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 2.0 tp_atr_mult: 4.0 description: ATR trailing stop (2.0x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.013
Best Continuous Score: 79.56

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 7 | 79.56 | 1.013 | +167.21% | -38.19% | 1.27 | 148 | accept | target_reached |
| 2 | 1 | -0.44 | 0.365 | +22.06% | -58.53% | 1.04 | 110 | continue | high_drawdown |
| 3 | 3 | -0.44 | 0.365 | +22.06% | -58.53% | 1.04 | 110 | continue | high_drawdown |
| 4 | 5 | -0.44 | 0.365 | +22.06% | -58.53% | 1.04 | 110 | continue | high_drawdown |
| 5 | 6 | -0.44 | 0.365 | +22.06% | -58.53% | 1.04 | 110 | continue | high_drawdown |
| 6 | 2 | -100.00 | -20.000 | -129.09% | -100.00% | 0.73 | 96 | continue | ruined |
| 7 | 4 | -100.00 | -20.000 | -98.55% | -100.00% | 0.71 | 89 | continue | ruined |