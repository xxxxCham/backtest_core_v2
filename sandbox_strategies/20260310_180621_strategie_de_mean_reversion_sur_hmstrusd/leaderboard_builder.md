# Leaderboard Builder - session 20260310_180621_strategie_de_mean_reversion_sur_hmstrusd

Objective: Strategie de Mean-reversion sur HMSTRUSDC 15m. Indicateurs : Bollinger Bands, ATR, RSI(14). Entree long quand prix tombe sous bande inferieure (2 std) et RSI < 30. Stop-loss = 1.5x ATR, take-profit = 2.5x ATR.
Strategy family: mean_reversion.
Hypothesis: Cette strategie combine l'usage des bandes de Bollinger pour identifier les extremums de prix avec le RSI pour confirmer la survente, maximisant ainsi les chances d'une reversion de tendance vers la moyenne.
Constraints: La strategie doit etre teste uniquement sur HMSTRUSDC; Utiliser un timeframe de 15 minutes
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -223.40% | -100.00% | 0.79 | 1087 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -170.73% | -100.00% | 0.76 | 628 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -77.69% | -100.00% | 0.79 | 344 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -109.54% | -100.00% | 0.77 | 516 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -109.54% | -100.00% | 0.77 | 516 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -77.69% | -100.00% | 0.79 | 344 | stop | ruined |