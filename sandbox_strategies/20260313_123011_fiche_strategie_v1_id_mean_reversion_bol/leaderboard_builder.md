# Leaderboard Builder - session 20260313_123011_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=42, std_dev=1.7) - rsi(period=11) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 20 - short: close > bollinger.upper and rsi > 75 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.0 tp_atr_mult: 5.0 description: ATR stop-loss (2.0x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.459
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | 0.459 | -38.97% | -92.43% | 0.93 | 295 | continue | ruined |
| 2 | 2 | -100.00 | -0.768 | -94.67% | -99.18% | 0.85 | 440 | continue | ruined |
| 3 | 3 | -100.00 | 0.420 | -42.90% | -93.58% | 0.91 | 243 | continue | ruined |
| 4 | 4 | -100.00 | -0.768 | -94.67% | -99.18% | 0.85 | 440 | continue | ruined |
| 5 | 5 | -100.00 | 0.420 | -42.90% | -93.58% | 0.91 | 243 | continue | ruined |
| 6 | 6 | -100.00 | -0.790 | -94.40% | -98.96% | 0.85 | 439 | stop | ruined |