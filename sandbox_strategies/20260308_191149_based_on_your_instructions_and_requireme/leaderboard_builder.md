# Leaderboard Builder - session 20260308_191149_based_on_your_instructions_and_requireme

Objective: Based on your instructions and requirements, here is a concise JSON output that represents the trading strategy:

```json
{
"action": "iterate",
"response": {
"objective": "\u901a\u8fc7\u66f4\u4e25\u683c\u7684\u5165\u5e02\u6761\u4ef6\u548c\u7a33\u5b9a\u7684\u98ce\u9669\u7ba1\u7406\uff0c\u63d0\u9ad8\u7b56\u7565\u7684\u7a33\u5b9a\u6027\u548c\u6d41\u52a8\u6027",
"rationale": "\u8be5\u7b56\u7565\u4f7f\u5f97\u6e05\u6670\uff0c\u4f46\u9700\u8981\u8fdb\u4e00\u6b65\u4f18\u5316\uff0c\u4ee5\u964d\u4f4e\u9ad8\u6ce2\u52a8\u6027(82%)\u548c\u5927\u5e45\u56de\u64a4(-35%)\uff0c\u4f18\u5316\u53ef\u4ee5\u901a\u8fc7\u63d0\u9ad8\u98ce\u9669\u63a7\u5236\u548c\u589e\u52a0\u76c8\u5229\u80fd\u529b\u7684\u4e00\u81f4\u6027\uff0c\u5b9e\u73b0",
"constraints": [
"\u9884\u6710\u6536\u76ca\u7387\u81f3\u5c11\u4e3a1.0",
"\u6700\u5927\u56de\u64a4\u964d\u4f4e\u5230\u5f53\u524d\u6c34\u4f4d\u4ee5\u4e0b(-35%)"
],
"strategy_family": "\u7ec4\u5408\u578b(\u7ed3\u5408\u52a8\u91cf\uff0c\u7a81\u7834\uff0c\u5747\u503c\u56de\u5f52\u7b56\u7565)"
}
}
```

### Explanation:
- **Objective:** The strategy aims to improve stability and liquidity through stricter entry conditions and risk management.
- **Rationale:** This approach demonstrates profitability, but it requires further optimization to reduce high wave activity (82%) and large drawdowns (-35%). Optimization can be achieved by improving risk control and increasing profit potential.
- **Constraints:**
- The minimum Sharpe ratio is set at 1.0.
- The maximum drawdown limit is set below the current water level (-35%).
- **Strategy Family:** Hybrid (Combining momentum, breakout, mean reversion strategies).

### Next Steps:
Since the strategy hasn't met the target Sharpe ratio and the best score is negative, the appropriate action is to **iterate**. The goal of further iterations will be to refine the strategy by incorporating stress tests, diverse historical data, and thorough validation to enhance reliability.

If you need more information or a different approach, please let me know!
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |
| 2 | 5 | -61.10 | -0.313 | -22.26% | -42.98% | 0.91 | 158 | continue | wrong_direction |
| 3 | 2 | -83.42 | -1.073 | -23.73% | -43.20% | 0.91 | 291 | continue | wrong_direction |
| 4 | 1 | -100.00 | -1.330 | -47.03% | -55.16% | 0.83 | 220 | continue | high_drawdown |
| 5 | 3 | -100.00 | -20.000 | -113.23% | -100.00% | 0.38 | 137 | continue | ruined |