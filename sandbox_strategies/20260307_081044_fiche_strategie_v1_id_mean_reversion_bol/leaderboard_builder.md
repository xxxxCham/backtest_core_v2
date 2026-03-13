# Leaderboard Builder - session 20260307_081044_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=10, std_dev=2.1) - rsi(period=12) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 80 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.0 tp_atr_mult: 3.0 description: ATR stop-loss (1.0x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 1.456
Best Continuous Score: 86.40

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 100.00 | 1.605 | +68.40% | -40.17% | 1.54 | 57 | continue | target_reached |
| 2 | 5 | 86.40 | 1.456 | +62.63% | -44.80% | 1.37 | 87 | continue | target_reached |
| 3 | 6 | 86.40 | 1.456 | +62.63% | -44.80% | 1.37 | 87 | continue | target_reached |
| 4 | 8 | 86.40 | 1.456 | +62.63% | -44.80% | 1.37 | 87 | continue | target_reached |
| 5 | 9 | 86.40 | 1.456 | +62.63% | -44.80% | 1.37 | 87 | continue | target_reached |
| 6 | 10 | 86.40 | 1.456 | +62.63% | -44.80% | 1.37 | 87 | continue | target_reached |
| 7 | 7 | 83.43 | 1.411 | +59.97% | -44.80% | 1.33 | 87 | continue | target_reached |
| 8 | 2 | -35.83 | -0.132 | -10.97% | -26.56% | 0.87 | 24 | continue | low_win_rate |
| 9 | 1 | -100.00 | -0.474 | -61.92% | -85.14% | 0.35 | 20 | continue | high_drawdown |