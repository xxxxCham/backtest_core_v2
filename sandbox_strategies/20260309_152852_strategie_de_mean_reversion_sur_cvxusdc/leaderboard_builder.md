# Leaderboard Builder - session 20260309_152852_strategie_de_mean_reversion_sur_cvxusdc

Objective: Strategie de Mean-reversion sur CVXUSDC 30m. Indicateurs : RSI(14), ATR. Utiliser RSI court terme (params rsi_period=3) extreme haut (> 90) comme signal d'entree short, repli anticipe. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: failed
Best Sharpe: 0.194
Best Continuous Score: 7.94

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 7.94 | 0.194 | +1.68% | -17.99% | 1.09 | 9 | continue | needs_work |
| 2 | 1 | -100.00 | -20.000 | -196.57% | -100.00% | 0.74 | 673 | continue | ruined |
| 3 | 2 | -100.00 | -20.000 | -306.89% | -100.00% | 0.63 | 935 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -138.57% | -100.00% | 0.75 | 461 | continue | ruined |
| 5 | 5 | -100.00 | -0.440 | -58.90% | -72.56% | 0.88 | 395 | continue | high_drawdown |
| 6 | 6 | -100.00 | -20.000 | -149.39% | -100.00% | 0.74 | 472 | continue | ruined |
| 7 | 7 | -100.00 | -1.252 | -66.68% | -74.88% | 0.82 | 390 | continue | high_drawdown |
| 8 | 9 | -100.00 | -20.000 | -221.48% | -100.00% | 0.72 | 689 | stop | ruined |