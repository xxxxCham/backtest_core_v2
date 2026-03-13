# Leaderboard Builder - session 20260313_112706_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=23, std_dev=2.4) - rsi(period=11) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 40 - short: close > bollinger.upper and rsi > 75 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: ATR stop-loss (2.0x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -640.12% | -100.00% | 0.72 | 2279 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -304.69% | -100.00% | 0.72 | 1062 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -369.85% | -100.00% | 0.72 | 1166 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -295.12% | -100.00% | 0.73 | 1064 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -370.83% | -100.00% | 0.72 | 1177 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -371.38% | -100.00% | 0.72 | 1163 | stop | ruined |