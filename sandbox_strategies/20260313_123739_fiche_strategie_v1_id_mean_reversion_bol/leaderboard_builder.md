# Leaderboard Builder - session 20260313_123739_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=22, std_dev=1.6) - rsi(period=15) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 65 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.0 tp_atr_mult: 4.0 description: ATR stop-loss (2.0x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.464
Best Continuous Score: 93.73

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 93.73 | 1.464 | +47.60% | -35.46% | 1.17 | 171 | accept | target_reached |
| 2 | 3 | 32.99 | 0.781 | +18.87% | -44.65% | 1.07 | 212 | continue | approaching_target |
| 3 | 1 | 17.50 | 0.404 | +4.42% | -35.46% | 1.01 | 174 | continue | marginal |
| 4 | 2 | -52.90 | -0.210 | -17.81% | -44.65% | 0.94 | 216 | continue | needs_work |