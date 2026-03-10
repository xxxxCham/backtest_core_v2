# Leaderboard Builder - session 20260308_195705_json_sessions_objective_improve_stabilit

Objective: json
{
"sessions": [
{
"objective": "Improve stability and liquidity through stricter entry conditions and better risk management.",
"rationale": "The current strategy lacks robustness due to high volatility and large drawdowns, necessitating further optimization in risk control and profit potential.",
"constraints": [
"Minimum Sharpe ratio of at least 1.0",
"Maximize the reduction of drawdowns below -35%"
],
"strategy_family": "hybrid",
"multi_llm_router_decision": {
"action": "iterate",
"confidence": 0.0,
"reason": "The current strategy does not meet the desired performance metrics, particularly in terms of Sharpe ratio and drawdown."
},
"multi_llm_role_outputs": {}
}
],
"instructions": [
"Target complex but realistic strategies.",
"Favor robust entry and risk management rules.",
"Avoid repeating the same exact market or timeframe unless justified."
],
"required_output": {
"objective": "one concise objective string",
"rationale": "short explanation of the edge",
"constraints": [
"constraint1",
"constraint2"
],
"strategy_family": "momentum | breakout | mean_reversion | hybrid"
}
}
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -37.30

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -37.30 | -0.420 | -11.23% | -31.36% | 0.90 | 112 | continue | needs_work |
| 2 | 1 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 3 | 4 | -92.02 | -0.761 | -22.87% | -55.87% | 0.93 | 289 | continue | high_drawdown |
| 4 | 3 | -100.00 | -20.000 | -183.82% | -100.00% | 0.59 | 523 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -100.32% | -100.00% | 0.60 | 307 | continue | ruined |
| 6 | 6 | -100.00 | -2.093 | -35.74% | -35.94% | 0.63 | 83 | stop | wrong_direction |