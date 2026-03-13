# Leaderboard Builder - session 20260313_100613_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=10, slow_period=26, signal_period=7) - rsi(period=8) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 40 and rsi < 70 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 3.0 tp_atr_mult: 3.0 description: ATR stop-loss (3.0x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -347.71% | -100.00% | 0.77 | 1138 | continue | ruined |
| 2 | 7 | -100.00 | -20.000 | -412.76% | -100.00% | 0.77 | 1382 | continue | ruined |
| 3 | 8 | -100.00 | -20.000 | -343.17% | -100.00% | 0.81 | 1353 | continue | ruined |
| 4 | 9 | -100.00 | -20.000 | -400.44% | -100.00% | 0.76 | 1294 | stop | ruined |