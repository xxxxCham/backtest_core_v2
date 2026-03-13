# Leaderboard Builder - session 20260312_123527_fiche_strategie_v1_id_mean_reversion_bol

Objective: FICHE_STRATEGIE v1 id: mean_reversion_bollinger_rsi archetype: mean_reversion_bollinger_rsi family: mean_reversion timeframe: side: both indicators: - bollinger(period=28, std_dev=2.6) - rsi(period=15) - atr(period=14) entry: - long: close < bollinger.lower and rsi < 25 - short: close > bollinger.upper and rsi > 75 exit: - condition: cross_any(close, bollinger.middle) or cross_any(rsi, 50) risk: stop_atr_mult: 2.25 tp_atr_mult: 5.0 description: ATR stop-loss (2.25x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.149
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | 100.00 | 1.149 | +40.31% | -15.22% | 1.46 | 47 | accept | target_reached |
| 2 | 2 | 47.68 | 0.568 | +14.29% | -17.31% | 1.16 | 52 | continue | approaching_target |
| 3 | 3 | -4.24 | 0.078 | +0.17% | -18.35% | 1.01 | 9 | continue | needs_work |
| 4 | 1 | -100.00 | -20.000 | -73.98% | -100.00% | 0.86 | 153 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -257.99% | -100.00% | 0.79 | 579 | continue | ruined |