# Leaderboard Builder - session 20260312_103936_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=8) - donchian(period=15) - atr(period=14) entry: - long: amplitude_hunter.score > 0.8 and close > donchian.upper - short: amplitude_hunter.score > 0.8 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.45 or cross_any(close, donchian.middle) risk: stop_atr_mult: 1.5 tp_atr_mult: 5.0 description: ATR stop-loss (1.5x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.933
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 98.52 | 0.933 | +67.28% | -27.63% | 14.88 | 3 | continue | insufficient_trades |
| 2 | 5 | 98.52 | 0.933 | +67.28% | -27.63% | 14.88 | 3 | continue | insufficient_trades |
| 3 | 8 | 98.52 | 0.933 | +67.28% | -27.63% | 14.88 | 3 | continue | insufficient_trades |
| 4 | 9 | 98.52 | 0.933 | +67.28% | -27.63% | 14.88 | 3 | continue | insufficient_trades |
| 5 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 6 | 7 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 7 | 1 | -69.19 | 0.318 | -11.97% | -54.43% | 0.82 | 5 | continue | high_drawdown |
| 8 | 6 | -69.19 | 0.318 | -11.97% | -54.43% | 0.82 | 5 | continue | high_drawdown |
| 9 | 10 | -69.19 | 0.318 | -11.97% | -54.43% | 0.82 | 5 | continue | high_drawdown |
| 10 | 3 | -100.00 | -20.000 | -132.70% | -100.00% | 0.50 | 26 | continue | ruined |