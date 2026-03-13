# Leaderboard Builder - session 20260313_162621_this_is_a_json_object_containing_informa

Objective: This is a JSON object containing information about various strategies, their objectives, indicators used, and performance metrics. The data includes:

1. An array of strategy objects, each with an objective, the related archetype (volatility, mean_reversion or hybrid), indicators used (amplitude_hunter, bollinger, donchian, rsi, atr), entry and exit conditions, risk management parameters, performance metrics like best sharpe ratio, best score, best return, best max drawdown, and pf, and various other details.
2. Instructions for creating effective strategies from the listed indicators.
3. Required checks to ensure the validity and completeness of a strategy objective.
4. The required output format for a strategy objective, including an objective string, rationale, constraints, and strategy family.
Status: failed
Best Sharpe: 0.256
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 3 | 3 | -88.69 | 0.256 | -32.09% | -75.02% | 0.95 | 365 | continue | overtrading |
| 4 | 1 | -100.00 | -20.000 | -104.72% | -100.00% | 0.75 | 110 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -9.06% | -100.00% | 0.99 | 195 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -104.72% | -100.00% | 0.75 | 110 | continue | ruined |