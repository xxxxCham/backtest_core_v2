# Leaderboard Builder - session 20260312_103035_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=49, std_dev=2.7) - rsi(period=15) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 40 - short: close > bollinger.upper and rsi > 60 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.75 tp_atr_mult: 5.0 description: ATR stop-loss (1.75x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: -1.612
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -133.75% | -100.00% | 0.83 | 842 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -218.75% | -100.00% | 0.74 | 780 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -125.59% | -100.00% | 0.77 | 657 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -218.75% | -100.00% | 0.74 | 780 | continue | ruined |
| 5 | 5 | -100.00 | -1.612 | -39.05% | -60.00% | 0.83 | 312 | continue | high_drawdown |
| 6 | 6 | -100.00 | -20.000 | -219.48% | -100.00% | 0.74 | 785 | stop | ruined |