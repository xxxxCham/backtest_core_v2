# Leaderboard Builder - session 20260312_105947_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=45, std_dev=3.0) - rsi(period=18) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 70 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.0 tp_atr_mult: 4.5 description: ATR stop-loss (2.0x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -0.815
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -403.97% | -100.00% | 0.66 | 1628 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -1186.36% | -100.00% | 0.40 | 2311 | continue | ruined |
| 3 | 3 | -100.00 | -1.793 | -94.05% | -94.11% | 0.62 | 421 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -934.61% | -100.00% | 0.60 | 3643 | continue | ruined |
| 5 | 5 | -100.00 | -0.815 | -97.31% | -98.00% | 0.65 | 418 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -248.20% | -100.00% | 0.63 | 1027 | stop | ruined |