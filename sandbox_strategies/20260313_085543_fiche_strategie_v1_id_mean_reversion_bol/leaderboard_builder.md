# Leaderboard Builder - session 20260313_085543_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=16, std_dev=2.2) - rsi(period=13) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 35 - short: close > bollinger.upper and rsi > 75 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.5 tp_atr_mult: 4.0 description: ATR stop-loss (1.5x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.554
Best Continuous Score: 28.01

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 28.01 | 0.486 | +36.81% | -50.40% | 1.04 | 522 | continue | overtrading |
| 2 | 10 | 21.01 | 0.383 | +17.95% | -41.79% | 1.03 | 298 | continue | needs_work |
| 3 | 7 | 18.59 | 0.554 | +46.62% | -69.69% | 1.06 | 380 | continue | overtrading |
| 4 | 8 | 10.37 | 0.350 | +10.04% | -42.03% | 1.02 | 298 | continue | needs_work |
| 5 | 3 | 3.37 | 0.463 | +17.79% | -54.44% | 1.02 | 480 | continue | overtrading |
| 6 | 5 | -3.27 | 0.298 | +0.02% | -42.33% | 1.00 | 295 | continue | marginal |
| 7 | 2 | -54.43 | 0.165 | -16.31% | -54.41% | 0.97 | 308 | continue | high_drawdown |
| 8 | 6 | -81.26 | 0.059 | -31.98% | -60.11% | 0.95 | 305 | continue | high_drawdown |
| 9 | 9 | -86.26 | 0.101 | -36.16% | -69.99% | 0.96 | 418 | continue | high_drawdown |
| 10 | 4 | -100.00 | -0.237 | -85.00% | -89.78% | 0.83 | 230 | continue | high_drawdown |