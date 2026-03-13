# Leaderboard Builder - session 20260307_093302_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=21, std_dev=1.9) - rsi(period=21) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 35 - short: close > bollinger.upper and rsi > 70 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.0 tp_atr_mult: 5.5 description: ATR stop-loss (1.0x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 1.096
Best Continuous Score: 95.37

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 7 | 100.00 | 1.957 | +63.93% | -25.32% | 1.40 | 98 | continue | low_win_rate |
| 2 | 9 | 95.37 | 1.096 | +41.71% | -24.02% | 1.41 | 53 | continue | low_win_rate |
| 3 | 3 | 12.71 | 0.620 | +10.19% | -44.29% | 1.06 | 92 | continue | low_win_rate |
| 4 | 2 | 9.66 | 0.632 | +9.13% | -47.87% | 1.04 | 103 | continue | approaching_target |
| 5 | 8 | 9.66 | 0.632 | +9.13% | -47.87% | 1.04 | 103 | continue | approaching_target |
| 6 | 5 | -38.60 | 0.120 | -10.05% | -41.98% | 0.90 | 53 | continue | low_win_rate |
| 7 | 1 | -40.13 | 0.553 | -5.97% | -55.55% | 0.97 | 100 | continue | high_drawdown |
| 8 | 10 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 9 | 6 | -100.00 | -1.417 | -68.13% | -77.59% | 0.80 | 234 | continue | high_drawdown |