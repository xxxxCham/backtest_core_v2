# Leaderboard Builder - session 20260313_110740_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=20, std_dev=2.4) - rsi(period=7) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 30 - short: close > bollinger.upper and rsi > 65 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.5 tp_atr_mult: 6.0 description: ATR stop-loss (2.5x) and take-profit (6.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.552
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 100.00 | 0.552 | +877.14% | -20.81% | 1.74 | 485 | continue | approaching_target |
| 2 | 4 | 100.00 | 0.552 | +877.14% | -20.81% | 1.74 | 485 | continue | approaching_target |
| 3 | 5 | 100.00 | 0.552 | +877.14% | -20.81% | 1.74 | 485 | continue | approaching_target |
| 4 | 6 | 100.00 | 0.552 | +877.14% | -20.81% | 1.74 | 485 | continue | approaching_target |
| 5 | 7 | 100.00 | 0.552 | +877.14% | -20.81% | 1.74 | 485 | continue | approaching_target |
| 6 | 9 | 100.00 | 0.552 | +877.38% | -20.79% | 1.74 | 485 | continue | approaching_target |
| 7 | 10 | 100.00 | 0.552 | +877.38% | -20.79% | 1.74 | 485 | continue | approaching_target |
| 8 | 1 | -100.00 | -20.000 | -1177.21% | -100.00% | 0.57 | 830 | continue | ruined |
| 9 | 2 | -100.00 | -20.000 | -223.93% | -100.00% | 0.69 | 400 | continue | ruined |
| 10 | 8 | -100.00 | -20.000 | -223.93% | -100.00% | 0.69 | 400 | continue | ruined |