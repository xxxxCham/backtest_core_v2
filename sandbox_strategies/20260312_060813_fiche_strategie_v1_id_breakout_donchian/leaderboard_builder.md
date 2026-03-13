# Leaderboard Builder - session 20260312_060813_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=20) - adx(period=20) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 25 - short: close < donchian.lower and adx.adx > 25 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 15 risk: stop_atr_mult: 1.75 tp_atr_mult: 3.5 description: ATR stop-loss (1.75x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 3 | 3 | -100.00 | -20.000 | -271.18% | -100.00% | 0.01 | 429 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -188.82% | -100.00% | 0.02 | 294 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -196.39% | -100.00% | 0.02 | 650 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -158.85% | -100.00% | 0.03 | 524 | stop | ruined |