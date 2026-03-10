# Leaderboard Builder - session 20260309_151456_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=8, slow_period=35, signal_period=10) - rsi(period=14) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 50 and rsi < 80 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 1.5 tp_atr_mult: 4.0 description: ATR stop-loss (1.5x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -100.00 | -20.000 | -10743.02% | -100.00% | 0.15 | 35320 | continue | ruined |
| 2 | 6 | -100.00 | -20.000 | -691.67% | -100.00% | 0.46 | 2298 | stop | ruined |