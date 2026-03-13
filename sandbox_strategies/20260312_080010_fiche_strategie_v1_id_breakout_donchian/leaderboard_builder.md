# Leaderboard Builder - session 20260312_080010_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=25) - adx(period=12) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 20 - short: close < donchian.lower and adx.adx > 20 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 15 risk: stop_atr_mult: 1.25 tp_atr_mult: 4.0 description: ATR stop-loss (1.25x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 5 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 6 | 3 | -100.00 | -20.000 | -710.24% | -100.00% | 0.70 | 2075 | continue | ruined |