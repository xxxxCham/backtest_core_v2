# Leaderboard Builder - session 20260313_101031_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=9, slow_period=28, signal_period=8) - rsi(period=14) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 35 and rsi < 65 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 2.75 tp_atr_mult: 5.0 description: ATR stop-loss (2.75x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 2 | 2 | -100.00 | -20.000 | -2083.27% | -100.00% | 0.66 | 7796 | continue | ruined |
| 3 | 4 | -100.00 | -20.000 | -1819.53% | -100.00% | 0.68 | 6851 | continue | ruined |
| 4 | 5 | -100.00 | -20.000 | -2083.27% | -100.00% | 0.66 | 7796 | continue | ruined |