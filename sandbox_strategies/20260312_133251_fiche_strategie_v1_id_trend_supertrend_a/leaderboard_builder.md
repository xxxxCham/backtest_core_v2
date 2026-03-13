# Leaderboard Builder - session 20260312_133251_fiche_strategie_v1_id_trend_supertrend_a

Objective: FICHE_STRATEGIE v1 id: trend_supertrend archetype: trend_supertrend family: trend timeframe: side: both indicators: - supertrend(atr_period=10, multiplier=3.5) - adx(period=16) - atr(period=14) entry: - long: supertrend.direction == 1 and adx.adx > 30 - short: supertrend.direction == -1 and adx.adx > 30 exit: - condition: direction_change(supertrend.direction) or adx.adx < 20 risk: stop_atr_mult: 2.75 tp_atr_mult: 5.0 description: ATR trailing stop (2.75x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -0.659
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -225.40% | -100.00% | 0.72 | 444 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -122.27% | -100.00% | 0.76 | 350 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -220.13% | -100.00% | 0.77 | 621 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -109.69% | -100.00% | 0.75 | 277 | continue | ruined |
| 5 | 5 | -100.00 | -0.659 | -57.24% | -69.46% | 0.86 | 259 | continue | high_drawdown |
| 6 | 6 | -100.00 | -1.150 | -51.87% | -64.79% | 0.77 | 228 | stop | high_drawdown |