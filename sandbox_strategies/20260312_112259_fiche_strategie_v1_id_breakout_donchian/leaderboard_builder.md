# Leaderboard Builder - session 20260312_112259_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=10) - adx(period=16) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 30 - short: close < donchian.lower and adx.adx > 30 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 20 risk: stop_atr_mult: 2.0 tp_atr_mult: 5.5 description: ATR stop-loss (2.0x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.546
Best Continuous Score: -20.95

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | -20.95 | 0.546 | +14.61% | -87.84% | 1.04 | 58 | continue | high_drawdown |
| 2 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 5 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 6 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 7 | 7 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 8 | 8 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 9 | 9 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |