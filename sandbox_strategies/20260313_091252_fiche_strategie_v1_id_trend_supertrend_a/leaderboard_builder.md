# Leaderboard Builder - session 20260313_091252_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=9, multiplier=2.5) - adx(period=20) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 35 - short: supertrend.direction == -1 and adx.adx > 35 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 2.75 tp_atr_mult: 3.5 description: ATR trailing stop (2.75x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.625
Best Continuous Score: -16.07

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | -16.07 | 0.625 | +3.71% | -65.97% | 1.03 | 23 | continue | high_drawdown |
| 2 | 1 | -100.00 | -20.000 | -129.70% | -100.00% | 0.00 | 5 | continue | ruined |
| 3 | 2 | -100.00 | -0.857 | -51.81% | -60.39% | 0.37 | 4 | continue | insufficient_trades |
| 4 | 3 | -100.00 | -20.000 | -102.06% | -100.00% | 0.35 | 14 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -129.70% | -100.00% | 0.00 | 5 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -129.70% | -100.00% | 0.00 | 5 | continue | ruined |
| 7 | 7 | -100.00 | -0.761 | -55.40% | -62.41% | 0.42 | 7 | continue | high_drawdown |
| 8 | 8 | -100.00 | -1.819 | -26.84% | -31.86% | 0.00 | 2 | continue | insufficient_trades |
| 9 | 9 | -100.00 | -0.761 | -55.40% | -62.41% | 0.42 | 7 | stop | high_drawdown |