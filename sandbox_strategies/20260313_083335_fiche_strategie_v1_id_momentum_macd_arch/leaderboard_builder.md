# Leaderboard Builder - session 20260313_083335_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=15, slow_period=31, signal_period=11) - rsi(period=16) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 45 and rsi < 75 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 1.25 tp_atr_mult: 5.5 description: ATR stop-loss (1.25x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -100.00 | -20.000 | -470.88% | -100.00% | 0.40 | 1077 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -470.88% | -100.00% | 0.40 | 1077 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -470.88% | -100.00% | 0.40 | 1077 | continue | ruined |
| 5 | 8 | -100.00 | -20.000 | -470.88% | -100.00% | 0.40 | 1077 | continue | ruined |
| 6 | 9 | -100.00 | -20.000 | -405.52% | -100.00% | 0.43 | 973 | stop | ruined |