# Leaderboard Builder - session 20260312_083550_strategie_de_mean_reversion_statarb_sur

Objective: Strategie de Mean-reversion / StatArb sur DOGSUSDC 1h. Indicateurs : Bollinger Bands (pour z-score), RSI(14), ATR. Entree long quand z-score (close - BB middle) / BB std < -2, entree short quand z-score > +2. Sortie retour a la moyenne. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 1 | -100.00 | -20.000 | -233.08% | -100.00% | 0.70 | 325 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -225.27% | -100.00% | 0.71 | 324 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -225.27% | -100.00% | 0.71 | 324 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -225.27% | -100.00% | 0.71 | 324 | stop | ruined |