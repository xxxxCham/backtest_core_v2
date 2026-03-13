# Leaderboard Builder - session 20260312_123902_fiche_strategie_v1_id_breakout_donchian

Objective: FICHE_STRATEGIE v1 id: breakout_donchian_adx archetype: breakout_donchian_adx family: breakout timeframe: side: both indicators: - donchian(period=20) - adx(period=10) - atr(period=14) entry: - long: close > donchian.upper and adx.adx > 30 - short: close < donchian.lower and adx.adx > 30 exit: - condition: cross_any(close, donchian.middle) or adx.adx < 20 risk: stop_atr_mult: 1.5 tp_atr_mult: 4.5 description: ATR stop-loss (1.5x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 1.113
Best Continuous Score: 70.01

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 70.01 | 1.058 | +58.94% | -49.07% | 1.47 | 41 | continue | target_reached |
| 2 | 7 | 66.43 | 1.113 | +67.69% | -54.95% | 1.52 | 42 | continue | high_drawdown |
| 3 | 5 | 58.77 | 0.810 | +33.90% | -42.05% | 1.26 | 45 | continue | approaching_target |
| 4 | 4 | 40.29 | 0.744 | +28.75% | -47.94% | 1.21 | 45 | continue | approaching_target |
| 5 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 6 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 7 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 8 | 8 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 9 | 9 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 10 | 10 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |