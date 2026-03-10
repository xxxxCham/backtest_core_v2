# Leaderboard Builder - session 20260308_174900_based_on_your_instructions_and_the_need

Objective: Based on your instructions and the need to generate a concise JSON output, here is the required information for the trading strategy:

```json
{
"objective": "Improve robustness and performance through better entry conditions and stable risk management.",
"rationale": "The strategy shows potential but requires further iterations to reduce high volatility (82%) and large drawdowns (-35%), which can be achieved by optimizing risk management rules and improving consistency in profitability.",
"constraints": [
"Maintain a target Sharpe ratio of at least 1.0.",
"Reduce the maximum drawdown significantly below the current level (-35%)."
],
"strategy_family": "hybrid"
}
```

### Explanation:
- **Objective**: To improve the strategy's robustness and performance through better entry conditions and stable risk management.
- **Rationale**: Despite showing potential, the current strategy needs further iterations to address high volatility (82%) and large drawdowns (-35%). Improving consistency in profitability can be achieved by optimizing risk management rules.
- **Constraints**:
- Maintain a target Sharpe ratio of at least 1.0.
- Reduce the maximum drawdown significantly below the current level of -35%.
- **Strategy Family**: Hybrid (combining elements from momentum, breakout, and mean reversion strategies to balance performance and risk).

This JSON output meets your specified requirements for an objective string, rationale explanation, constraints, and strategy family classification.
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -2528.51% | -100.00% | 0.56 | 8209 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -1089.22% | -100.00% | 0.56 | 3159 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -1044.16% | -100.00% | 0.55 | 2978 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -1209.39% | -100.00% | 0.56 | 3547 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -1089.22% | -100.00% | 0.56 | 3159 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -1061.15% | -100.00% | 0.56 | 3075 | stop | ruined |