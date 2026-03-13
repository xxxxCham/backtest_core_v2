# Leaderboard Builder - session 20260312_093454_strategie_de_momentum_sur_tstusdc_1h_ind

Objective: Strategie de Momentum sur TSTUSDC 1h. Indicateurs : EMA(20), ATR. Calculer la pente de EMA(20) via np.diff. Entree long quand la pente est positive et accelere. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: failed
Best Sharpe: 0.529
Best Continuous Score: -19.62

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -19.62 | 0.529 | +6.04% | -59.41% | 1.04 | 24 | continue | high_drawdown |
| 2 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 4 | -44.85 | 0.497 | -1.06% | -63.25% | 0.99 | 24 | continue | high_drawdown |
| 4 | 1 | -100.00 | -20.000 | -117.37% | -100.00% | 0.65 | 52 | continue | ruined |
| 5 | 3 | -100.00 | -20.000 | -159.08% | -100.00% | 0.48 | 32 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -159.08% | -100.00% | 0.48 | 32 | continue | ruined |
| 7 | 7 | -100.00 | -20.000 | -117.37% | -100.00% | 0.65 | 52 | continue | ruined |
| 8 | 8 | -100.00 | -0.189 | -35.04% | -68.05% | 0.78 | 15 | continue | high_drawdown |
| 9 | 9 | -100.00 | -20.000 | -184.46% | -100.00% | 0.39 | 23 | stop | ruined |