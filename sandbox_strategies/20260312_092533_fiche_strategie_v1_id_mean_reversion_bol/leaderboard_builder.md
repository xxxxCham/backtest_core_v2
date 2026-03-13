# Leaderboard Builder - session 20260312_092533_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=49, std_dev=2.7) - rsi(period=14) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 80 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.0 tp_atr_mult: 5.5 description: ATR stop-loss (1.0x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -1.192
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -509.89% | -100.00% | 0.74 | 1964 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -207.17% | -100.00% | 0.79 | 736 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -401.19% | -100.00% | 0.68 | 1312 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -132.36% | -100.00% | 0.76 | 672 | continue | ruined |
| 5 | 5 | -100.00 | -1.569 | -75.16% | -77.40% | 0.67 | 258 | continue | high_drawdown |
| 6 | 6 | -100.00 | -1.192 | -89.18% | -89.35% | 0.63 | 266 | stop | high_drawdown |