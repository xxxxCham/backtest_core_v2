# Leaderboard Builder - session 20260312_115234_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=15, slow_period=22, signal_period=10) - rsi(period=16) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 40 and rsi < 70 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.0 tp_atr_mult: 2.5 description: ATR stop-loss (2.0x) and take-profit (2.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.902
Best Continuous Score: 32.46

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 32.46 | 0.159 | +3.19% | -19.86% | 1.99 | 6 | continue | needs_work |
| 2 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 8 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 1 | -86.53 | -0.281 | -22.28% | -35.71% | 0.37 | 13 | continue | needs_work |
| 5 | 3 | -88.52 | 0.080 | -24.71% | -56.60% | 0.85 | 13 | continue | high_drawdown |
| 6 | 5 | -100.00 | 0.902 | -6.92% | -97.73% | 0.97 | 26 | continue | ruined |
| 7 | 6 | -100.00 | -20.000 | -229.23% | -100.00% | 0.42 | 31 | continue | ruined |
| 8 | 7 | -100.00 | -20.000 | -88.13% | -100.00% | 0.82 | 47 | continue | ruined |
| 9 | 9 | -100.00 | -20.000 | -57.55% | -100.00% | 0.87 | 54 | stop | ruined |