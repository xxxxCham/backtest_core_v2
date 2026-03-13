# Leaderboard Builder - session 20260313_174514_fiche_strategie_v1_id_momentum_breakout

Objective: FICHE_STRATEGIE v1 id: momentum_breakout_ichimoku archetype: momentum_breakout_ichimoku family: momentum timeframe: 1h symbol: NEARUSDC indicators: - ichimoku(tenkan_period=9, kijun_period=26, senkou_span_b_period=52) - volume_oscillator(short_period=5, long_period=20) - atr(period=14) entry: - long: close > ichimoku.cloud_top and volume_oscillator > 0 and close > ichimoku.kijun - short: close < ichimoku.cloud_bottom and volume_oscillator < 0 and close < ichimoku.kijun exit: - condition: cross_any(close, ichimoku.kijun) or volume_oscillator.cross_zero() risk: stop_atr_mult: 2.0 tp_atr_mult: 4.0 description: Ichimoku cloud breakout with volume confirmation and Kijun-sen support/resistance
Strategy family: momentum.
Hypothesis: Exploits momentum breakouts above/below Ichimoku cloud with volume confirmation, using the Kijun-sen line as dynamic support/resistance for robust trend-following entries
Constraints: no_lookahead: true; only_registry_indicators: true
Status: max_iterations
Best Sharpe: 0.601
Best Continuous Score: 19.33

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 19.33 | 0.373 | +230.00% | -72.65% | 1.24 | 250 | continue | high_drawdown |
| 2 | 6 | 18.89 | 0.479 | +283.65% | -74.11% | 1.15 | 696 | continue | high_drawdown |
| 3 | 1 | 18.25 | 0.458 | +319.76% | -82.62% | 1.25 | 376 | continue | high_drawdown |
| 4 | 7 | 17.14 | 0.365 | +142.42% | -65.96% | 1.09 | 390 | continue | overtrading |
| 5 | 3 | 16.98 | 0.441 | +301.34% | -83.73% | 1.23 | 371 | continue | high_drawdown |
| 6 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 7 | 10 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 8 | 2 | -60.01 | 0.601 | +292.60% | -99.23% | 1.20 | 414 | continue | ruined |
| 9 | 8 | -65.22 | 0.510 | +173.95% | -97.63% | 1.15 | 310 | continue | ruined |
| 10 | 9 | -100.00 | -20.000 | -584.09% | -100.00% | 0.53 | 225 | continue | ruined |