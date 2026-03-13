# Leaderboard Builder - session 20260312_131445_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=43, std_dev=2.7) - rsi(period=19) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 40 - short: close > bollinger.upper and rsi > 60 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.0 tp_atr_mult: 5.5 description: ATR stop-loss (2.0x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.855
Best Continuous Score: 79.69

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 79.69 | 0.855 | +38.62% | -26.49% | 1.18 | 106 | continue | approaching_target |
| 2 | 8 | 79.69 | 0.855 | +38.62% | -26.49% | 1.18 | 106 | continue | approaching_target |
| 3 | 2 | 27.69 | 0.301 | +5.79% | -19.66% | 1.07 | 52 | continue | needs_work |
| 4 | 9 | -31.48 | 0.104 | -7.32% | -43.42% | 0.97 | 147 | continue | needs_work |
| 5 | 5 | -47.88 | 0.537 | -2.83% | -74.44% | 1.00 | 310 | continue | overtrading |
| 6 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 7 | 1 | -100.00 | -20.000 | -245.53% | -100.00% | 0.82 | 573 | continue | ruined |
| 8 | 3 | -100.00 | -20.000 | -193.45% | -100.00% | 0.70 | 312 | continue | ruined |
| 9 | 7 | -100.00 | -20.000 | -89.53% | -100.00% | 0.90 | 349 | continue | ruined |
| 10 | 10 | -100.00 | -20.000 | -175.22% | -100.00% | 0.79 | 418 | continue | ruined |