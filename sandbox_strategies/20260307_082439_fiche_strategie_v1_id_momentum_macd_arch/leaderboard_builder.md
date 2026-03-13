# Leaderboard Builder - session 20260307_082439_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=9, slow_period=20, signal_period=11) - rsi(period=15) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 35 and rsi < 70 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 1.5 tp_atr_mult: 5.0 description: ATR stop-loss (1.5x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.796
Best Continuous Score: 73.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 73.00 | 0.796 | +105.87% | -40.52% | 2.20 | 9 | continue | approaching_target |
| 2 | 3 | 73.00 | 0.796 | +105.87% | -40.52% | 2.20 | 9 | continue | approaching_target |
| 3 | 4 | 73.00 | 0.796 | +105.87% | -40.52% | 2.20 | 9 | continue | approaching_target |
| 4 | 5 | 73.00 | 0.796 | +105.87% | -40.52% | 2.20 | 9 | continue | approaching_target |
| 5 | 6 | 73.00 | 0.796 | +105.87% | -40.52% | 2.20 | 9 | continue | approaching_target |
| 6 | 2 | 63.51 | 0.666 | +72.03% | -40.52% | 1.59 | 10 | continue | approaching_target |
| 7 | 9 | 41.43 | 0.741 | +99.35% | -62.75% | 1.44 | 33 | continue | high_drawdown |
| 8 | 7 | 39.05 | 0.585 | +53.23% | -56.27% | 1.60 | 9 | continue | high_drawdown |
| 9 | 10 | -59.72 | 0.845 | +62.59% | -95.35% | 1.36 | 18 | continue | ruined |