# Leaderboard Builder - session 20260313_095729_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=40, std_dev=1.9) - rsi(period=20) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 65 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.25 tp_atr_mult: 6.0 description: ATR stop-loss (2.25x) and take-profit (6.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.051
Best Continuous Score: 81.09

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | 81.09 | 1.051 | +113.59% | -37.20% | 1.26 | 202 | accept | target_reached |
| 2 | 1 | 73.06 | 0.985 | +94.27% | -39.13% | 1.19 | 243 | continue | approaching_target |
| 3 | 3 | 51.41 | 0.889 | +97.33% | -59.73% | 1.42 | 80 | continue | high_drawdown |
| 4 | 2 | -22.83 | 0.360 | +7.20% | -65.32% | 1.01 | 435 | continue | overtrading |
| 5 | 4 | -100.00 | -20.000 | -219.91% | -100.00% | 0.73 | 513 | continue | ruined |