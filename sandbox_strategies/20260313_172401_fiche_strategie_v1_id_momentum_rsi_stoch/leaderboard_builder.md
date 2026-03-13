# Leaderboard Builder - session 20260313_172401_fiche_strategie_v1_id_momentum_rsi_stoch

Objective: FICHE_STRATEGIE v1 id: momentum_rsi_stochastic archetype: momentum_rsi_stochastic family: momentum timeframe: 4h symbol: LAYERUSDC indicators: - rsi(period=7) - stochastic(k_period=5, d_period=3, smoothing=3) entry: - long: rsi < 20 and stochastic.k < 20 and stochastic.d < 20 - short: rsi > 80 and stochastic.k > 80 and stochastic.d > 80 exit: - condition: cross_any(stochastic.k, stochastic.d) risk: stop_atr_mult: 1.5 tp_atr_mult: 3.0 description: ATR stop-loss (1.5x) and take-profit (3.0x). Constraints: - no_lookahead: true - only_registry_indicators: true
Strategy family: momentum.
Hypothesis: The strategy exploits momentum by identifying oversold/overbought conditions with RSI and Stochastic oscillators, allowing for a robust entry into trending markets.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: failed
Best Sharpe: 0.681
Best Continuous Score: 62.17

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 9 | 62.17 | 0.583 | +15.47% | -9.37% | 4.65 | 2 | continue | insufficient_trades |
| 2 | 6 | 39.54 | 0.681 | +52.77% | -70.06% | 1.89 | 8 | continue | high_drawdown |
| 3 | 7 | 23.54 | 0.239 | +5.40% | -23.51% | 1.36 | 2 | continue | insufficient_trades |
| 4 | 4 | 13.34 | 0.598 | +29.76% | -70.06% | 1.54 | 6 | continue | high_drawdown |
| 5 | 8 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 6 | 10 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 7 | 3 | -49.26 | 0.196 | -4.06% | -43.85% | 0.80 | 5 | continue | needs_work |
| 8 | 1 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 9 | 5 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 10 | 2 | -74.39 | 0.087 | -12.76% | -51.38% | 0.77 | 5 | continue | high_drawdown |