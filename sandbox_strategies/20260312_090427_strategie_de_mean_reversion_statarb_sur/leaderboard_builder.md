# Leaderboard Builder - session 20260312_090427_strategie_de_mean_reversion_statarb_sur

Objective: Strategie de Mean-reversion / StatArb sur ASTERUSDC 15m. Indicateurs : Bollinger Bands (pour z-score), RSI(14), ATR. Entree long quand z-score (close - BB middle) / BB std < -2, entree short quand z-score > +2. Sortie retour a la moyenne. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: failed
Best Sharpe: -0.028
Best Continuous Score: -46.91

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | -46.91 | -0.028 | -9.55% | -50.53% | 0.96 | 135 | continue | high_drawdown |
| 2 | 1 | -100.00 | -1.057 | -45.11% | -66.09% | 0.88 | 294 | continue | high_drawdown |
| 3 | 2 | -100.00 | -20.000 | -133.25% | -100.00% | 0.75 | 545 | continue | ruined |
| 4 | 3 | -100.00 | -1.057 | -45.11% | -66.09% | 0.88 | 294 | continue | high_drawdown |
| 5 | 4 | -100.00 | -0.915 | -40.96% | -63.60% | 0.89 | 292 | continue | high_drawdown |
| 6 | 6 | -100.00 | -20.000 | -133.25% | -100.00% | 0.75 | 545 | stop | ruined |