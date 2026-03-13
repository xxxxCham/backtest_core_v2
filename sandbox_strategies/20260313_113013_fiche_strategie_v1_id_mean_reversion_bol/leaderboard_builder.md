# Leaderboard Builder - session 20260313_113013_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=17, std_dev=1.8) - rsi(period=17) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 20 - short: close > bollinger.upper and rsi > 60 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 1.75 tp_atr_mult: 3.5 description: ATR stop-loss (1.75x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.989
Best Continuous Score: 53.50

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 9 | 53.50 | 0.989 | +112.12% | -55.97% | 1.27 | 194 | continue | high_drawdown |
| 2 | 3 | 36.80 | 0.610 | +55.56% | -53.86% | 1.08 | 322 | continue | high_drawdown |
| 3 | 1 | 33.04 | 0.603 | +54.70% | -56.24% | 1.08 | 312 | continue | high_drawdown |
| 4 | 7 | -15.84 | 0.280 | +9.19% | -57.80% | 1.08 | 34 | continue | high_drawdown |
| 5 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 6 | 10 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 7 | 4 | -88.70 | -0.647 | -24.50% | -37.45% | 0.58 | 33 | continue | wrong_direction |
| 8 | 2 | -100.00 | -20.000 | -74.63% | -100.00% | 0.87 | 250 | continue | ruined |
| 9 | 6 | -100.00 | -20.000 | -67.64% | -100.00% | 0.90 | 303 | continue | ruined |
| 10 | 8 | -100.00 | -20.000 | -124.52% | -100.00% | 0.72 | 371 | continue | ruined |