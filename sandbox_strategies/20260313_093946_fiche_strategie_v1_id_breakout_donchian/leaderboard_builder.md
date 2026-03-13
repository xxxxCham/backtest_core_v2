# Leaderboard Builder - session 20260313_093946_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=35) - adx(period=12) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 30 - short: close < donchian.lower and adx.adx > 30 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 25 risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: ATR stop-loss (2.0x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 5 | 4 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 6 | 1 | -100.00 | -20.000 | -868.82% | -100.00% | 0.73 | 2441 | continue | ruined |