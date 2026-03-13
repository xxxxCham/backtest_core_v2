# Leaderboard Builder - session 20260313_081550_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=13, slow_period=27, signal_period=12) - rsi(period=19) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 45 and rsi < 70 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.25 tp_atr_mult: 3.5 description: ATR stop-loss (2.25x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -100.00 | -20.000 | -78.13% | -100.00% | 0.91 | 733 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -196.98% | -100.00% | 0.83 | 894 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -190.11% | -100.00% | 0.83 | 917 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -78.13% | -100.00% | 0.91 | 733 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -141.79% | -100.00% | 0.73 | 351 | stop | ruined |