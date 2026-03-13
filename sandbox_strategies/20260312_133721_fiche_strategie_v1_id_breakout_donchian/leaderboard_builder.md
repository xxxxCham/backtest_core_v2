# Leaderboard Builder - session 20260312_133721_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=35) - adx(period=10) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 25 - short: close < donchian.lower and adx.adx > 25 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 15 risk: stop_atr_mult: 1.5 tp_atr_mult: 4.0 description: ATR stop-loss (1.5x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.186
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 3 | -54.85 | 0.186 | -6.84% | -63.06% | 0.98 | 155 | continue | high_drawdown |
| 5 | 5 | -100.00 | -20.000 | -255.78% | -100.00% | 0.69 | 298 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -138.79% | -100.00% | 0.75 | 238 | stop | ruined |