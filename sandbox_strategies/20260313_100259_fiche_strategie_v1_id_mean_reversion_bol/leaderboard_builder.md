# Leaderboard Builder - session 20260313_100259_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=10, std_dev=2.9) - rsi(period=20) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 20 - short: close > bollinger.upper and rsi > 65 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.75 tp_atr_mult: 2.5 description: ATR stop-loss (1.75x) and take-profit (2.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -42.69% | -100.00% | 0.91 | 276 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -121.57% | -100.00% | 0.88 | 678 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -106.92% | -100.00% | 0.84 | 472 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -124.02% | -100.00% | 0.88 | 679 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -106.09% | -100.00% | 0.85 | 473 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -121.57% | -100.00% | 0.88 | 678 | stop | ruined |