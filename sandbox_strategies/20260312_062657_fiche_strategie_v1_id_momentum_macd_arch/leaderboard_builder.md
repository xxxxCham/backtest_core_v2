# Leaderboard Builder - session 20260312_062657_fiche_strategie_v1_id_momentum_macd_arch

Objective: FICHE_STRATEGIE v1 id: momentum_macd archetype: momentum_macd family: momentum timeframe: side: both indicators: - macd(fast_period=14, slow_period=33, signal_period=12) - rsi(period=16) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and rsi > 40 and rsi < 70 - short: cross_down(macd.macd, macd.signal) and rsi > 30 and rsi < 60 exit: - condition: sign_change(macd.histogram) or rsi > 80 or rsi < 20 risk: stop_atr_mult: 1.5 tp_atr_mult: 3.0 description: ATR stop-loss (1.5x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: running
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -100.00 | -20.000 | -214.94% | -100.00% | 0.59 | 891 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -495.09% | -100.00% | 0.45 | 1351 | continue | ruined |