# Leaderboard Builder - session 20260307_175709_generate_profits_by_identifying_and_trad

Objective: Generate profits by identifying and trading breakouts above the upper Bollinger Band with confirmation from a positive MACD crossover, using TRXUSDC on the 1h timeframe.
Strategy family: breakout.
Hypothesis: This strategy capitalizes on breakout momentum where price action exceeds typical volatility levels indicated by Bollinger Bands, while the MACD ensures that we are catching the initial upward trend continuation.
Constraints: Only trade when both conditions (upper band breakout and positive MACD crossover) are met within a single candlestick formation to avoid false signals.; Implement stop-loss at the lower Bollinger Band level to limit downside risk.
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -100.00 | -20.000 | -240.15% | -100.00% | 0.62 | 347 | continue | ruined |
| 2 | 3 | -100.00 | -0.575 | -55.30% | -77.11% | 0.68 | 94 | continue | high_drawdown |
| 3 | 4 | -100.00 | -0.719 | -29.80% | -54.34% | 0.67 | 44 | continue | high_drawdown |
| 4 | 5 | -100.00 | -20.000 | -150.15% | -100.00% | 0.73 | 250 | continue | ruined |
| 5 | 6 | -100.00 | -0.419 | -57.02% | -78.41% | 0.71 | 103 | stop | high_drawdown |