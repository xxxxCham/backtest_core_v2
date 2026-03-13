# Leaderboard Builder - session 20260310_181310_json_objective_strategie_de_mean_reversi

Objective: json
{
"objective": "Strategie de Mean-reversion sur HMSTRUSDC 15m. Indicateurs : Bollinger Bands, ATR, RSI(14). Entree long quand prix tombe sous bande inferieure (2 std) et RSI < 30. Stop-loss = 1.5x ATR, take-profit = 2.5x ATR.",
"rationale": "Cette strategie combine l'usage des bandes de Bollinger pour identifier les extremums de prix avec le RSI pour confirmer la survente, maximisant ainsi les chances d'une reversion de tendance vers la moyenne.",
"constraints": [
"La strategie doit etre teste uniquement sur HMSTRUSDC",
"Utiliser un timeframe de 15 minutes"
],
"strategy_family": "mean_reversion"
}
Status: max_iterations
Best Sharpe: 0.810
Best Continuous Score: 49.85

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 49.85 | 0.810 | +30.38% | -45.94% | 1.20 | 107 | continue | approaching_target |
| 2 | 4 | 49.85 | 0.810 | +30.38% | -45.94% | 1.20 | 107 | continue | approaching_target |
| 3 | 6 | 49.85 | 0.810 | +30.38% | -45.94% | 1.20 | 107 | continue | approaching_target |
| 4 | 8 | 49.85 | 0.810 | +30.38% | -45.94% | 1.20 | 107 | continue | approaching_target |
| 5 | 1 | 27.88 | 0.632 | +18.44% | -47.12% | 1.13 | 107 | continue | approaching_target |
| 6 | 3 | 27.88 | 0.632 | +18.44% | -47.12% | 1.13 | 107 | continue | approaching_target |
| 7 | 5 | 27.88 | 0.632 | +18.44% | -47.12% | 1.13 | 107 | continue | approaching_target |
| 8 | 7 | 27.88 | 0.632 | +18.44% | -47.12% | 1.13 | 107 | continue | approaching_target |
| 9 | 9 | 27.88 | 0.632 | +18.44% | -47.12% | 1.13 | 107 | continue | approaching_target |
| 10 | 10 | 27.88 | 0.632 | +18.44% | -47.12% | 1.13 | 107 | continue | approaching_target |