# Leaderboard Builder - session 20260312_060136_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=40) - adx(period=16) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 35 - short: close < donchian.lower and adx.adx > 35 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 15 risk: stop_atr_mult: 1.75 tp_atr_mult: 6.0 description: ATR stop-loss (1.75x) and take-profit (6.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -226.88% | -100.00% | 0.69 | 714 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -272.82% | -100.00% | 0.63 | 573 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -272.82% | -100.00% | 0.63 | 573 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -159.39% | -100.00% | 0.54 | 279 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -87.59% | -100.00% | 0.60 | 217 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -272.82% | -100.00% | 0.63 | 573 | stop | ruined |