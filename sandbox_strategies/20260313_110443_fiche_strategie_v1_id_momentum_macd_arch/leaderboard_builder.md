# Leaderboard Builder - session 20260313_110443_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=11, slow_period=33, signal_period=7) - rsi(period=19) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 35 and rsi < 60 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.5 tp_atr_mult: 2.5 description: ATR stop-loss (2.5x) and take-profit (2.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -100.00 | -20.000 | -1524.91% | -100.00% | 0.63 | 4763 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -1267.51% | -100.00% | 0.65 | 3971 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -1465.85% | -100.00% | 0.63 | 4533 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -1465.85% | -100.00% | 0.63 | 4533 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -1059.65% | -100.00% | 0.68 | 2900 | stop | ruined |