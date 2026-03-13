# Leaderboard Builder - session 20260312_122108_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=15, std_dev=2.3) - rsi(period=17) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 40 - short: close > bollinger.upper and rsi > 65 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.5 tp_atr_mult: 5.0 description: ATR stop-loss (2.5x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -0.504
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -174.15% | -100.00% | 0.86 | 866 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -461.58% | -100.00% | 0.78 | 2006 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -410.92% | -100.00% | 0.73 | 1511 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -668.05% | -100.00% | 0.83 | 3095 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -172.89% | -100.00% | 0.73 | 741 | continue | ruined |
| 6 | 6 | -100.00 | -0.504 | -50.50% | -61.09% | 0.85 | 294 | stop | high_drawdown |