# Leaderboard Builder - session 20260313_082157_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=10, std_dev=2.4) - rsi(period=18) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 40 - short: close > bollinger.upper and rsi > 75 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.25 tp_atr_mult: 4.5 description: ATR stop-loss (1.25x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.501
Best Continuous Score: 41.18

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 8 | 41.18 | 0.491 | +42.21% | -49.11% | 1.07 | 301 | continue | needs_work |
| 2 | 10 | 41.18 | 0.491 | +42.21% | -49.11% | 1.07 | 301 | continue | needs_work |
| 3 | 4 | 39.78 | 0.501 | +45.33% | -49.84% | 1.06 | 367 | continue | approaching_target |
| 4 | 2 | 33.08 | 0.469 | +37.68% | -52.15% | 1.06 | 302 | continue | high_drawdown |
| 5 | 6 | 33.08 | 0.469 | +37.68% | -52.15% | 1.06 | 302 | continue | high_drawdown |
| 6 | 1 | -100.00 | -20.000 | -112.51% | -100.00% | 0.89 | 507 | continue | ruined |
| 7 | 3 | -100.00 | -20.000 | -75.97% | -100.00% | 0.89 | 307 | continue | ruined |
| 8 | 5 | -100.00 | -20.000 | -111.54% | -100.00% | 0.87 | 408 | continue | ruined |
| 9 | 7 | -100.00 | -20.000 | -75.97% | -100.00% | 0.89 | 307 | continue | ruined |
| 10 | 9 | -100.00 | -20.000 | -111.53% | -100.00% | 0.89 | 499 | continue | ruined |