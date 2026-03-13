# Leaderboard Builder - session 20260312_132541_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=19, multiplier=3.5) - adx(period=12) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 20 - short: supertrend.direction == -1 and adx.adx > 20 exit: - condition: direction_change(supertrend.direction) or adx.adx < 15 risk: stop_atr_mult: 1.25 tp_atr_mult: 3.0 description: ATR trailing stop (1.25x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.687
Best Continuous Score: 6.73

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 46.33 | 0.687 | +71.71% | -54.47% | 1.21 | 86 | continue | high_drawdown |
| 2 | 4 | 6.73 | 0.366 | +18.82% | -52.67% | 1.04 | 121 | continue | high_drawdown |
| 3 | 10 | -27.77 | 0.121 | -8.33% | -39.43% | 0.96 | 50 | continue | needs_work |
| 4 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 5 | 9 | -61.16 | 0.385 | -16.84% | -64.80% | 0.98 | 196 | continue | high_drawdown |
| 6 | 3 | -87.19 | -5.000 | -10.00% | -25.00% | 0.50 | 3496 | continue | overtrading |
| 7 | 1 | -88.69 | 0.382 | -66.18% | -88.80% | 0.92 | 206 | continue | high_drawdown |
| 8 | 7 | -95.49 | 0.065 | -57.24% | -75.85% | 0.91 | 179 | continue | high_drawdown |
| 9 | 5 | -100.00 | -20.000 | -90.55% | -100.00% | 0.87 | 167 | continue | ruined |
| 10 | 8 | -100.00 | -0.371 | -56.65% | -80.21% | 0.84 | 85 | continue | high_drawdown |