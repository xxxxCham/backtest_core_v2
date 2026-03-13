# Leaderboard Builder - session 20260312_103436_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=46) - donchian(period=35) - atr(period=14) entry: - long: amplitude_hunter.score > 0.85 and close > donchian.upper - short: amplitude_hunter.score > 0.85 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.35 or cross_any(close, donchian.middle) risk: stop_atr_mult: 1.5 tp_atr_mult: 3.0 description: ATR stop-loss (1.5x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.984
Best Continuous Score: 89.21

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 89.21 | 0.984 | +129.18% | -36.86% | 2.07 | 17 | continue | approaching_target |
| 2 | 7 | 87.37 | 0.872 | +102.75% | -30.86% | 1.41 | 50 | continue | approaching_target |
| 3 | 1 | 75.40 | 0.761 | +94.43% | -41.90% | 1.71 | 17 | continue | approaching_target |
| 4 | 5 | 75.40 | 0.761 | +94.43% | -41.90% | 1.71 | 17 | continue | approaching_target |
| 5 | 2 | 66.54 | 0.608 | +60.15% | -40.12% | 1.37 | 23 | continue | approaching_target |
| 6 | 9 | 30.26 | 0.457 | +36.67% | -51.39% | 1.31 | 13 | continue | high_drawdown |
| 7 | 10 | 18.04 | 0.440 | +33.89% | -55.63% | 1.26 | 16 | continue | high_drawdown |
| 8 | 4 | 14.80 | 0.452 | +35.83% | -60.71% | 1.26 | 15 | continue | high_drawdown |
| 9 | 8 | -74.26 | 0.168 | -16.80% | -69.79% | 0.96 | 86 | continue | high_drawdown |
| 10 | 6 | -89.98 | 0.176 | -14.18% | -73.61% | 0.90 | 18 | continue | high_drawdown |