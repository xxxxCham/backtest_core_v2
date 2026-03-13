# Leaderboard Builder - session 20260312_085218_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=45) - adx(period=20) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 25 - short: close < donchian.lower and adx.adx > 25 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 20 risk: stop_atr_mult: 1.0 tp_atr_mult: 5.5 description: ATR stop-loss (1.0x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 5 | 3 | -100.00 | -0.521 | -57.20% | -65.36% | 0.65 | 62 | continue | high_drawdown |
| 6 | 6 | -100.00 | -0.668 | -47.62% | -54.90% | 0.73 | 80 | stop | high_drawdown |