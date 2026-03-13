# Leaderboard Builder - session 20260313_092816_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=13, std_dev=1.6) - rsi(period=12) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 35 - short: close > bollinger.upper and rsi > 60 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.75 tp_atr_mult: 3.5 description: ATR stop-loss (1.75x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.531
Best Continuous Score: 32.76

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 32.76 | 0.531 | +17.27% | -39.72% | 1.10 | 122 | continue | approaching_target |
| 2 | 5 | 32.76 | 0.531 | +17.27% | -39.72% | 1.10 | 122 | continue | approaching_target |
| 3 | 10 | 32.76 | 0.531 | +17.27% | -39.72% | 1.10 | 122 | continue | approaching_target |
| 4 | 1 | -19.58 | 0.285 | -1.38% | -45.49% | 1.00 | 370 | continue | needs_work |
| 5 | 8 | -49.23 | -0.194 | -19.61% | -40.22% | 0.93 | 152 | continue | needs_work |
| 6 | 4 | -57.81 | 0.113 | -19.21% | -53.63% | 0.97 | 381 | continue | high_drawdown |
| 7 | 9 | -57.81 | 0.113 | -19.21% | -53.63% | 0.97 | 381 | continue | high_drawdown |
| 8 | 3 | -72.28 | -0.300 | -27.56% | -46.89% | 0.90 | 167 | continue | wrong_direction |
| 9 | 6 | -72.28 | -0.300 | -27.56% | -46.89% | 0.90 | 167 | continue | wrong_direction |
| 10 | 7 | -72.28 | -0.300 | -27.56% | -46.89% | 0.90 | 167 | continue | wrong_direction |