# Leaderboard Builder - session 20260312_114605_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=9, slow_period=24, signal_period=12) - rsi(period=8) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 45 and rsi < 75 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.75 tp_atr_mult: 4.5 description: ATR stop-loss (2.75x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.542
Best Continuous Score: 31.56

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 31.56 | 0.452 | +34.92% | -49.22% | 1.04 | 308 | continue | needs_work |
| 2 | 6 | 22.57 | 0.542 | +54.60% | -70.41% | 1.08 | 152 | continue | high_drawdown |
| 3 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 7 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 5 | 4 | -97.56 | 0.044 | -45.28% | -80.31% | 0.91 | 86 | continue | high_drawdown |
| 6 | 3 | -100.00 | -20.000 | -155.43% | -100.00% | 0.38 | 48 | continue | ruined |
| 7 | 5 | -100.00 | -20.000 | -106.19% | -100.00% | 0.87 | 162 | continue | ruined |
| 8 | 8 | -100.00 | -20.000 | -88.10% | -100.00% | 0.87 | 161 | continue | ruined |
| 9 | 9 | -100.00 | -20.000 | -204.17% | -100.00% | 0.56 | 115 | continue | ruined |
| 10 | 10 | -100.00 | -20.000 | -158.09% | -100.00% | 0.81 | 156 | continue | ruined |