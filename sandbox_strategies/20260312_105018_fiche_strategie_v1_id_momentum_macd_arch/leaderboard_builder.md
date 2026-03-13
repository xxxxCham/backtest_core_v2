# Leaderboard Builder - session 20260312_105018_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=10, slow_period=21, signal_period=10) - rsi(period=17) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 30 and rsi < 65 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.75 tp_atr_mult: 4.0 description: ATR stop-loss (2.75x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -100.00 | -20.000 | -180.27% | -100.00% | 0.87 | 599 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -435.35% | -100.00% | 0.79 | 1151 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -680.63% | -100.00% | 0.71 | 1458 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -454.25% | -100.00% | 0.81 | 1133 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -680.63% | -100.00% | 0.71 | 1458 | stop | ruined |