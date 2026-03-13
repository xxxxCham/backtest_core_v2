# Leaderboard Builder - session 20260312_062112_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=50) - adx(period=19) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 25 - short: close < donchian.lower and adx.adx > 25 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 20 risk: stop_atr_mult: 2.75 tp_atr_mult: 4.5 description: ATR stop-loss (2.75x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.404
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 6 | -70.63 | 0.404 | -17.55% | -88.84% | 0.97 | 186 | stop | high_drawdown |
| 3 | 2 | -100.00 | -20.000 | -151.51% | -100.00% | 0.31 | 98 | continue | ruined |
| 4 | 3 | -100.00 | 0.154 | -73.98% | -88.97% | 0.06 | 39 | continue | high_drawdown |
| 5 | 4 | -100.00 | -20.000 | -119.82% | -100.00% | 0.61 | 169 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -224.40% | -100.00% | 0.73 | 274 | continue | ruined |