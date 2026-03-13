# Leaderboard Builder - session 20260313_120959_strategie_de_momentum_sur_1000cheemsusdc

Objective: Strategie de Momentum sur 1000CHEEMSUSDC 1w. Indicateurs : EMA(20), ATR. Calculer la pente de EMA(20) via np.diff. Entree short quand la pente est negative et accelere. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: success
Best Sharpe: 3.978
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 100.00 | 3.978 | +464.89% | -18.60% | 4.97 | 137 | accept | target_reached |
| 2 | 1 | -100.00 | -20.000 | -186.13% | -100.00% | 0.81 | 418 | continue | ruined |