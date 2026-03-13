# Leaderboard Builder - session 20260313_095953_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=13, slow_period=31, signal_period=10) - rsi(period=14) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 35 and rsi < 60 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.0 tp_atr_mult: 2.0 description: ATR stop-loss (2.0x) and take-profit (2.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -100.00 | -20.000 | -681.66% | -100.00% | 0.79 | 2765 | continue | ruined |
| 3 | 2 | -100.00 | -20.000 | -1564.74% | -100.00% | 0.77 | 5871 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -1323.70% | -100.00% | 0.79 | 5391 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -681.66% | -100.00% | 0.79 | 2765 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -681.66% | -100.00% | 0.79 | 2765 | stop | ruined |