# Leaderboard Builder - session 20260312_075618_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=14, slow_period=32, signal_period=7) - rsi(period=14) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 40 and rsi < 60 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.25 tp_atr_mult: 5.5 description: ATR stop-loss (2.25x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.006
Best Continuous Score: -50.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |
| 2 | 3 | -52.85 | 0.006 | -17.51% | -46.29% | 0.92 | 92 | continue | needs_work |
| 3 | 1 | -100.00 | -3.192 | -83.35% | -86.80% | 0.25 | 33 | continue | high_drawdown |
| 4 | 2 | -100.00 | -20.000 | -122.61% | -100.00% | 0.68 | 257 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -196.37% | -100.00% | 0.62 | 303 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -139.84% | -100.00% | 0.76 | 376 | continue | ruined |