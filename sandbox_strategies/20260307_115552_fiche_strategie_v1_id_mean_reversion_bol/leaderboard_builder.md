# Leaderboard Builder - session 20260307_115552_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=32, std_dev=2.6) - rsi(period=13) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 40 - short: close > bollinger.upper and rsi > 70 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.5 tp_atr_mult: 5.5 description: ATR stop-loss (2.5x) and take-profit (5.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.424
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 48.72 | 1.080 | +56.20% | -56.34% | 1.12 | 187 | continue | high_drawdown |
| 2 | 5 | 37.46 | 0.711 | +29.93% | -44.87% | 1.05 | 448 | continue | overtrading |
| 3 | 2 | -87.71 | 0.400 | -30.49% | -80.65% | 0.92 | 118 | continue | high_drawdown |
| 4 | 7 | -87.71 | 0.400 | -30.49% | -80.65% | 0.92 | 118 | continue | high_drawdown |
| 5 | 1 | -100.00 | -20.000 | -137.09% | -100.00% | 0.73 | 260 | continue | ruined |
| 6 | 4 | -100.00 | -20.000 | -70.09% | -100.00% | 0.71 | 68 | continue | ruined |
| 7 | 9 | -100.00 | 0.424 | -59.00% | -92.40% | 0.87 | 151 | stop | ruined |