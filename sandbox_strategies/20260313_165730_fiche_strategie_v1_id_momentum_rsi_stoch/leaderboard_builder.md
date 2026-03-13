# Leaderboard Builder - session 20260313_165730_fiche_strategie_v1_id_momentum_rsi_stoch

Objective: FICHE_STRATEGIE v1 id: momentum_rsi_stochastic archetype: momentum_rsi_stochastic family: momentum timeframe: 4h symbol: LAYERUSDC indicators: - rsi(period=7) - stochastic(k_period=5, d_period=3, smoothing=3) entry: - long: rsi < 20 and stochastic.k < 20 and stochastic.d < 20 - short: rsi > 80 and stochastic.k > 80 and stochastic.d > 80 exit: - condition: cross_any(stochastic.k, stochastic.d) risk: stop_atr_mult: 1.5 tp_atr_mult: 3.0 description: ATR stop-loss (1.5x) and take-profit (3.0x). Constraints: - no_lookahead: true - only_registry_indicators: true
Strategy family: momentum.
Hypothesis: The strategy exploits momentum by identifying oversold/overbought conditions with RSI and Stochastic oscillators, allowing for a robust entry into trending markets.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: failed
Best Sharpe: 2.250
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 100.00 | 2.250 | +22.43% | -8.43% | 2.39 | 13 | continue | target_reached |
| 2 | 4 | 56.94 | 0.962 | +8.70% | -9.94% | 1.29 | 24 | continue | approaching_target |
| 3 | 5 | 43.88 | 0.744 | +6.66% | -10.62% | 1.21 | 24 | continue | approaching_target |
| 4 | 3 | -64.50 | -0.592 | -22.24% | -37.48% | 0.82 | 65 | continue | wrong_direction |
| 5 | 2 | -64.56 | -0.888 | -9.13% | -20.58% | 0.72 | 16 | continue | needs_work |
| 6 | 7 | -67.04 | -0.586 | -24.63% | -39.44% | 0.87 | 126 | continue | wrong_direction |
| 7 | 1 | -78.87 | -0.997 | -10.36% | -19.59% | 0.54 | 12 | continue | needs_work |
| 8 | 8 | -100.00 | -20.000 | -170.56% | -100.00% | 0.56 | 266 | stop | ruined |