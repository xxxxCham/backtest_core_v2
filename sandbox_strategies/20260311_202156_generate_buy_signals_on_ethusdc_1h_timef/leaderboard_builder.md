# Leaderboard Builder - session 20260311_202156_generate_buy_signals_on_ethusdc_1h_timef

Objective: Generate buy signals on ETHUSDC 1h timeframe when the 12-period MACD line crosses above the 26-period signal line, indicating a potential shift in short-term momentum and a likely upward price movement.
Strategy family: momentum.
Hypothesis: MACD line crossovers often precede short-term price increases as buying pressure strengthens.
Constraints: Only execute buy orders.; Maximum position size per trade: 0.25% of total capital.
Status: failed
Best Sharpe: -3.869
Best Continuous Score: -84.84

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -84.84 | -3.869 | -13.56% | -19.95% | 0.50 | 48 | stop | losing_per_trade |
| 2 | 1 | -100.00 | -5.819 | -31.45% | -34.32% | 0.53 | 99 | continue | wrong_direction |