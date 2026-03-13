# Leaderboard Builder - session 20260312_110431_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=22, std_dev=2.7) - rsi(period=15) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 60 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.5 tp_atr_mult: 4.0 description: ATR stop-loss (1.5x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.796
Best Continuous Score: 88.82

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 88.82 | 0.796 | +78.14% | -36.92% | 1.59 | 45 | continue | approaching_target |
| 2 | 6 | 66.74 | 0.529 | +19.78% | -12.51% | 2.04 | 10 | continue | approaching_target |
| 3 | 1 | 56.89 | 0.741 | +87.14% | -57.02% | 1.56 | 47 | continue | high_drawdown |
| 4 | 7 | 55.55 | 0.447 | +16.29% | -21.82% | 2.01 | 5 | continue | needs_work |
| 5 | 4 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 6 | 3 | -96.30 | -0.894 | -19.80% | -19.80% | 0.00 | 3 | continue | insufficient_trades |
| 7 | 2 | -100.00 | 0.103 | -30.60% | -80.17% | 0.79 | 29 | continue | high_drawdown |
| 8 | 5 | -100.00 | -20.000 | -22.56% | -100.00% | 0.96 | 122 | continue | ruined |
| 9 | 8 | -100.00 | -20.000 | -80.89% | -100.00% | 0.84 | 137 | continue | ruined |
| 10 | 9 | -100.00 | -20.000 | -75.06% | -100.00% | 0.84 | 118 | continue | ruined |