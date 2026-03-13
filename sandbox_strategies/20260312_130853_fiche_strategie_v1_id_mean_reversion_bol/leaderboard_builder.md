# Leaderboard Builder - session 20260312_130853_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=38, std_dev=2.6) - rsi(period=18) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 30 - short: close > bollinger.upper and rsi > 65 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.25 tp_atr_mult: 2.5 description: ATR stop-loss (2.25x) and take-profit (2.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -1281.61% | -100.00% | 0.62 | 5149 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -282.01% | -100.00% | 0.44 | 969 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -671.07% | -100.00% | 0.64 | 3038 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -345.15% | -100.00% | 0.68 | 1529 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -751.16% | -100.00% | 0.65 | 3207 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -649.48% | -100.00% | 0.50 | 2480 | stop | ruined |