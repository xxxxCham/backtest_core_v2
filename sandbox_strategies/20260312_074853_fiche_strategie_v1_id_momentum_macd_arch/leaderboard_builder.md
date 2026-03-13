# Leaderboard Builder - session 20260312_074853_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=12, slow_period=31, signal_period=10) - rsi(period=10) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 30 and rsi < 70 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.0 tp_atr_mult: 2.0 description: ATR stop-loss (2.0x) and take-profit (2.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.034
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 100.00 | 1.034 | +166.31% | -34.80% | 1.92 | 27 | accept | target_reached |
| 2 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 5 | 1 | -100.00 | -20.000 | -211.59% | -100.00% | 0.31 | 20 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -210.35% | -100.00% | 0.46 | 32 | continue | ruined |