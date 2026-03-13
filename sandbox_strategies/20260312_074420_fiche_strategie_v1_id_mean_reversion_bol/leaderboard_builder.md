# Leaderboard Builder - session 20260312_074420_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=48, std_dev=2.0) - rsi(period=18) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 40 - short: close > bollinger.upper and rsi > 65 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.25 tp_atr_mult: 4.0 description: ATR stop-loss (2.25x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -74.24

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 2 | 6 | -74.24 | -0.545 | -15.62% | -32.08% | 0.62 | 7 | stop | needs_work |
| 3 | 3 | -96.51 | -0.505 | -24.33% | -44.07% | 0.57 | 11 | continue | needs_work |
| 4 | 1 | -100.00 | -1.016 | -44.92% | -60.68% | 0.36 | 8 | continue | high_drawdown |
| 5 | 2 | -100.00 | -1.782 | -24.58% | -25.98% | 0.00 | 2 | continue | insufficient_trades |
| 6 | 4 | -100.00 | -1.016 | -44.92% | -60.68% | 0.36 | 8 | continue | high_drawdown |