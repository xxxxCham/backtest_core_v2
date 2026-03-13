# Leaderboard Builder - session 20260313_121417_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=10, slow_period=31, signal_period=9) - rsi(period=20) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 45 and rsi < 70 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 1.0 tp_atr_mult: 3.5 description: ATR stop-loss (1.0x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -100.00 | -20.000 | -188.83% | -100.00% | 0.81 | 723 | continue | ruined |
| 3 | 4 | -100.00 | -20.000 | -204.43% | -100.00% | 0.79 | 718 | continue | ruined |
| 4 | 5 | -100.00 | -20.000 | -188.83% | -100.00% | 0.81 | 723 | continue | ruined |
| 5 | 6 | -100.00 | -20.000 | -188.83% | -100.00% | 0.81 | 723 | stop | ruined |