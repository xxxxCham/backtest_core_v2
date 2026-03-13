# Leaderboard Builder - session 20260313_093652_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=12, slow_period=24, signal_period=12) - rsi(period=19) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 35 and rsi < 75 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.75 tp_atr_mult: 3.5 description: ATR stop-loss (2.75x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 3 | -100.00 | -20.000 | -177.24% | -100.00% | 0.84 | 875 | continue | ruined |
| 3 | 4 | -100.00 | -20.000 | -198.51% | -100.00% | 0.72 | 369 | continue | ruined |
| 4 | 6 | -100.00 | -20.000 | -165.47% | -100.00% | 0.85 | 866 | stop | ruined |