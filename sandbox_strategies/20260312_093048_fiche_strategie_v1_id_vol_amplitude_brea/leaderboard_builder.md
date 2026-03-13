# Leaderboard Builder - session 20260312_093048_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=49) - donchian(period=25) - atr(period=14) entry: - long: amplitude_hunter.score > 0.85 and close > donchian.upper - short: amplitude_hunter.score > 0.85 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.4 or cross_any(close, donchian.middle) risk: stop_atr_mult: 1.25 tp_atr_mult: 3.0 description: ATR stop-loss (1.25x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.645
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 3 | -57.37 | 0.205 | -10.72% | -63.00% | 0.99 | 416 | continue | overtrading |
| 3 | 4 | -57.37 | 0.205 | -10.72% | -63.00% | 0.99 | 416 | continue | overtrading |
| 4 | 2 | -68.41 | 0.645 | -20.97% | -88.36% | 0.98 | 661 | continue | overtrading |
| 5 | 1 | -100.00 | -0.224 | -65.85% | -83.71% | 0.90 | 312 | continue | high_drawdown |
| 6 | 6 | -100.00 | -0.224 | -65.85% | -83.71% | 0.90 | 312 | stop | high_drawdown |