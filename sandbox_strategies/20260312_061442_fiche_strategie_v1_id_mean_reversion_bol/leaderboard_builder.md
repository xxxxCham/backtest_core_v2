# Leaderboard Builder - session 20260312_061442_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=37, std_dev=1.6) - rsi(period=21) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 80 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.25 tp_atr_mult: 4.5 description: ATR stop-loss (2.25x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.991
Best Continuous Score: 96.74

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 2 | 2 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 3 | 3 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 4 | 4 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 5 | 5 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 6 | 6 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 7 | 7 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 8 | 8 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 9 | 9 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |
| 10 | 10 | 96.74 | 0.991 | +103.55% | -39.53% | 2.02 | 44 | continue | approaching_target |