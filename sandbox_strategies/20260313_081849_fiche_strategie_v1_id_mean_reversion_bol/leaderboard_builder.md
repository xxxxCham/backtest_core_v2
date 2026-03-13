# Leaderboard Builder - session 20260313_081849_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=39, std_dev=2.0) - rsi(period=19) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 75 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.25 tp_atr_mult: 5.0 description: ATR stop-loss (1.25x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -0.037
Best Continuous Score: -55.73

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -55.73 | -0.037 | -12.28% | -41.58% | 0.82 | 21 | continue | low_win_rate |
| 2 | 3 | -55.73 | -0.037 | -12.28% | -41.58% | 0.82 | 21 | continue | low_win_rate |
| 3 | 5 | -55.73 | -0.037 | -12.28% | -41.58% | 0.82 | 21 | continue | low_win_rate |
| 4 | 2 | -100.00 | -0.211 | -32.05% | -77.61% | 0.84 | 71 | continue | high_drawdown |
| 5 | 4 | -100.00 | -0.180 | -34.74% | -75.19% | 0.85 | 90 | continue | high_drawdown |
| 6 | 6 | -100.00 | -0.180 | -34.74% | -75.19% | 0.85 | 90 | stop | high_drawdown |