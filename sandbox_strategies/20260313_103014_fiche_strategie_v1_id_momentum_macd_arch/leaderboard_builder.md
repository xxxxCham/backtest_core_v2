# Leaderboard Builder - session 20260313_103014_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=10, slow_period=27, signal_period=10) - rsi(period=18) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 40 and rsi < 65 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.0 tp_atr_mult: 4.5 description: ATR stop-loss (2.0x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 3 | 3 | -100.00 | -20.000 | -1671.38% | -100.00% | 0.57 | 2367 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -351.30% | -100.00% | 0.80 | 1067 | continue | ruined |