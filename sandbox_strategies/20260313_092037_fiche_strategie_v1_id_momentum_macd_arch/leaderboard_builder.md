# Leaderboard Builder - session 20260313_092037_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=12, slow_period=32, signal_period=8) - rsi(period=12) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 30 and rsi < 60 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.75 tp_atr_mult: 3.0 description: ATR stop-loss (2.75x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -100.00 | -20.000 | -307.00% | -100.00% | 0.85 | 1164 | continue | ruined |
| 2 | 3 | -100.00 | -20.000 | -488.34% | -100.00% | 0.80 | 1446 | continue | ruined |
| 3 | 4 | -100.00 | -20.000 | -307.00% | -100.00% | 0.85 | 1164 | continue | ruined |
| 4 | 7 | -100.00 | -20.000 | -307.00% | -100.00% | 0.85 | 1164 | continue | ruined |
| 5 | 9 | -100.00 | -20.000 | -307.00% | -100.00% | 0.85 | 1164 | stop | ruined |