# Leaderboard Builder - session 20260312_080314_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=6) - donchian(period=45) - atr(period=14) entry: - long: amplitude_hunter.score > 0.8 and close > donchian.upper - short: amplitude_hunter.score > 0.8 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.45 or cross_any(close, donchian.middle) risk: stop_atr_mult: 1.75 tp_atr_mult: 4.5 description: ATR stop-loss (1.75x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: 1.137
Best Continuous Score: 88.18

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 9 | 88.18 | 1.137 | +56.50% | -30.32% | 1.22 | 132 | accept | target_reached |
| 2 | 4 | 80.60 | 0.987 | +45.94% | -33.48% | 1.19 | 136 | continue | approaching_target |
| 3 | 6 | 80.60 | 0.987 | +45.94% | -33.48% | 1.19 | 136 | continue | approaching_target |
| 4 | 8 | 75.80 | 0.910 | +38.46% | -33.69% | 1.16 | 139 | continue | approaching_target |
| 5 | 1 | 73.19 | 0.855 | +38.91% | -34.91% | 1.15 | 137 | continue | approaching_target |
| 6 | 5 | 46.13 | 0.688 | +26.10% | -39.04% | 1.11 | 139 | continue | approaching_target |
| 7 | 7 | 43.33 | 0.704 | +28.09% | -43.10% | 1.12 | 137 | continue | approaching_target |
| 8 | 2 | 36.43 | 0.605 | +21.77% | -40.13% | 1.09 | 140 | continue | approaching_target |
| 9 | 3 | 36.43 | 0.605 | +21.77% | -40.13% | 1.09 | 140 | continue | approaching_target |