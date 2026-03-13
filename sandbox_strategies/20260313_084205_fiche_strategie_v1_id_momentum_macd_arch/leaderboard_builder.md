# Leaderboard Builder - session 20260313_084205_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=14, slow_period=32, signal_period=10) - rsi(period=14) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 35 and rsi < 80 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.75 tp_atr_mult: 4.0 description: ATR stop-loss (2.75x) and take-profit (4.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.148
Best Continuous Score: 4.84

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 4.84 | 0.148 | +8.52% | -42.68% | 1.03 | 91 | continue | needs_work |
| 2 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 5 | -100.00 | -20.000 | -925.76% | -100.00% | 0.80 | 3836 | continue | ruined |
| 4 | 7 | -100.00 | -20.000 | -528.00% | -100.00% | 0.84 | 1195 | continue | ruined |
| 5 | 8 | -100.00 | -20.000 | -1121.05% | -100.00% | 0.76 | 3940 | continue | ruined |
| 6 | 9 | -100.00 | -20.000 | -344.45% | -100.00% | 0.88 | 1625 | stop | ruined |