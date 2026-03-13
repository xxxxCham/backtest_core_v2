# Leaderboard Builder - session 20260312_134110_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=20) - adx(period=18) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 35 - short: close < donchian.lower and adx.adx > 35 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 25 risk: stop_atr_mult: 2.75 tp_atr_mult: 4.0 description: ATR stop-loss (2.75x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.166
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 5 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 6 | 5 | -65.09 | 0.166 | -5.18% | -60.43% | 0.97 | 18 | continue | high_drawdown |