# Leaderboard Builder - session 20260312_100626_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=34, std_dev=1.9) - rsi(period=7) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 30 - short: close > bollinger.upper and rsi > 75 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.25 tp_atr_mult: 6.0 description: ATR stop-loss (2.25x) and take-profit (6.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.555
Best Continuous Score: 46.25

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 46.25 | 0.555 | +4.74% | -2.32% | 3.00 | 12 | continue | approaching_target |
| 2 | 1 | -100.00 | -20.000 | -551.89% | -100.00% | 0.10 | 2047 | continue | ruined |
| 3 | 2 | -100.00 | -20.000 | -112.79% | -100.00% | 0.07 | 415 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -205.83% | -100.00% | 0.23 | 915 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -102.00% | -100.00% | 0.24 | 422 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -102.69% | -100.00% | 0.10 | 381 | continue | ruined |
| 7 | 7 | -100.00 | -20.000 | -132.45% | -100.00% | 0.13 | 534 | continue | ruined |
| 8 | 8 | -100.00 | -20.000 | -112.79% | -100.00% | 0.07 | 415 | continue | ruined |
| 9 | 9 | -100.00 | -20.000 | -461.43% | -100.00% | 0.12 | 1763 | stop | ruined |