# Leaderboard Builder - session 20260313_090840_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=9) - donchian(period=15) - atr(period=14) entry: - long: amplitude_hunter.score > 0.55 and close > donchian.upper - short: amplitude_hunter.score > 0.55 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.2 or cross_any(close, donchian.middle) risk: stop_atr_mult: 2.75 tp_atr_mult: 5.0 description: ATR stop-loss (2.75x) and take-profit (5.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.856
Best Continuous Score: 43.01

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 43.01 | 0.856 | +9.34% | -25.48% | 1.03 | 190 | continue | approaching_target |
| 2 | 5 | 43.01 | 0.856 | +9.34% | -25.48% | 1.03 | 190 | continue | approaching_target |
| 3 | 6 | 43.01 | 0.856 | +9.34% | -25.48% | 1.03 | 190 | continue | approaching_target |
| 4 | 7 | 43.01 | 0.856 | +9.34% | -25.48% | 1.03 | 190 | continue | approaching_target |
| 5 | 8 | 43.01 | 0.856 | +9.34% | -25.48% | 1.03 | 190 | continue | approaching_target |
| 6 | 9 | 43.01 | 0.856 | +9.34% | -25.48% | 1.03 | 190 | continue | approaching_target |
| 7 | 10 | 43.01 | 0.856 | +9.34% | -25.48% | 1.03 | 190 | continue | approaching_target |
| 8 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 9 | 1 | -100.00 | -3.736 | -89.04% | -89.04% | 0.60 | 103 | continue | high_drawdown |
| 10 | 3 | -100.00 | -20.000 | -199.74% | -100.00% | 0.60 | 457 | continue | ruined |