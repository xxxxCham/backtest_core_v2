# Leaderboard Builder - session 20260313_094642_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=10) - adx(period=15) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 25 - short: close < donchian.lower and adx.adx > 25 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 15 risk: stop_atr_mult: 1.75 tp_atr_mult: 2.0 description: ATR stop-loss (1.75x) and take-profit (2.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 5 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 6 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |