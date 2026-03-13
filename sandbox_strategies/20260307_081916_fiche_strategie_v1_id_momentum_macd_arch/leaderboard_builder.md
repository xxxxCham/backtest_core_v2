# Leaderboard Builder - session 20260307_081916_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=12, slow_period=25, signal_period=12) - rsi(period=17) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 35 and rsi < 80 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.5 tp_atr_mult: 3.0 description: ATR stop-loss (2.5x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.346
Best Continuous Score: -0.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | -0.00 | 0.346 | +4.89% | -44.31% | 1.04 | 36 | continue | marginal |
| 2 | 5 | -0.00 | 0.346 | +4.89% | -44.31% | 1.04 | 36 | continue | marginal |
| 3 | 6 | -0.00 | 0.346 | +4.89% | -44.31% | 1.04 | 36 | continue | marginal |
| 4 | 7 | -0.00 | 0.346 | +4.89% | -44.31% | 1.04 | 36 | continue | marginal |
| 5 | 8 | -0.00 | 0.346 | +4.89% | -44.31% | 1.04 | 36 | continue | marginal |
| 6 | 9 | -0.00 | 0.346 | +4.89% | -44.31% | 1.04 | 36 | continue | marginal |
| 7 | 10 | -0.00 | 0.346 | +4.89% | -44.31% | 1.04 | 36 | continue | marginal |
| 8 | 1 | -100.00 | -0.758 | -96.32% | -96.32% | 0.27 | 12 | continue | ruined |
| 9 | 3 | -100.00 | -20.000 | -83.93% | -100.00% | 0.61 | 109 | continue | ruined |