# Leaderboard Builder - session 20260307_075110_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=26, std_dev=2.3) - rsi(period=16) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 35 - short: close > bollinger.upper and rsi > 65 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.25 tp_atr_mult: 5.5 description: ATR stop-loss (2.25x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.268
Best Continuous Score: -26.99

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 9 | 77.62 | 0.689 | +111.35% | -41.82% | 1.65 | 20 | continue | approaching_target |
| 2 | 2 | 47.81 | 0.517 | +51.42% | -52.04% | 1.54 | 17 | continue | high_drawdown |
| 3 | 8 | 44.15 | 0.528 | +66.90% | -51.04% | 1.29 | 50 | continue | high_drawdown |
| 4 | 4 | -26.99 | 0.268 | +5.93% | -54.29% | 1.04 | 18 | continue | high_drawdown |
| 5 | 5 | -26.99 | 0.268 | +5.93% | -54.29% | 1.04 | 18 | continue | high_drawdown |
| 6 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 7 | 7 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 8 | 1 | -100.00 | 0.251 | -88.54% | -96.07% | 0.67 | 37 | continue | ruined |
| 9 | 3 | -100.00 | 0.122 | -24.18% | -70.59% | 0.86 | 16 | continue | high_drawdown |
| 10 | 10 | -100.00 | 0.122 | -24.18% | -70.59% | 0.86 | 16 | continue | high_drawdown |