# Leaderboard Builder - session 20260309_154740_strategie_de_mean_reversion_sur_grtusdc

Objective: Strategie de Mean-reversion sur GRTUSDC 15m. Indicateurs : Bollinger Bands (ecart type), ATR. Entree long quand prix tombe sous bande inferieure (ecart type extreme). Retour attendu vers la moyenne. Stop-loss = 1.0x ATR, take-profit = 2.0x ATR.
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -76.70

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -76.70 | 0.000 | -4.60% | -63.28% | 0.93 | 6 | continue | high_drawdown |
| 2 | 3 | -87.91 | -0.722 | -2.70% | -59.47% | 0.96 | 7 | continue | high_drawdown |
| 3 | 1 | -100.00 | -20.000 | -110.01% | -100.00% | 0.54 | 433 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -272.20% | -100.00% | 0.52 | 1058 | continue | ruined |
| 5 | 5 | -100.00 | -1.685 | -43.75% | -86.46% | 0.79 | 204 | continue | high_drawdown |
| 6 | 6 | -100.00 | -20.000 | -272.20% | -100.00% | 0.52 | 1058 | stop | ruined |