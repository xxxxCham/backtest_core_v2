# Leaderboard Builder - session 20260313_081424_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=50, std_dev=2.0) - rsi(period=15) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 75 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.5 tp_atr_mult: 2.5 description: ATR stop-loss (1.5x) and take-profit (2.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.246
Best Continuous Score: 82.80

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 82.80 | 1.246 | +17.05% | -8.64% | 1.44 | 32 | accept | target_reached |
| 2 | 1 | 20.84 | 0.282 | +2.76% | -14.04% | 1.05 | 38 | continue | marginal |
| 3 | 2 | -83.35 | -0.660 | -30.41% | -42.32% | 0.80 | 99 | continue | wrong_direction |