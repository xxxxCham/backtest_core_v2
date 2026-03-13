# Leaderboard Builder - session 20260313_124404_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=12, slow_period=33, signal_period=9) - rsi(period=11) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 45 and rsi < 70 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.25 tp_atr_mult: 3.0 description: ATR stop-loss (2.25x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: running
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -1480.02% | -100.00% | 0.55 | 4556 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -212.80% | -100.00% | 0.66 | 736 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -1436.82% | -100.00% | 0.55 | 4497 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -662.74% | -100.00% | 0.63 | 2266 | continue | ruined |