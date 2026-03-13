# Leaderboard Builder - session 20260312_122956_strategie_de_momentum_sur_neousdc_30m_in

Objective: Strategie de Momentum sur NEOUSDC 30m. Indicateurs : EMA(20), ATR. Calculer la pente de EMA(20) via np.diff. Entree long quand la pente est positive et accelere. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: max_iterations
Best Sharpe: 1.207
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | 100.00 | 1.207 | +92.66% | -33.17% | 1.88 | 20 | continue | target_reached |
| 2 | 3 | 97.16 | 0.989 | +65.76% | -31.55% | 1.65 | 20 | continue | approaching_target |
| 3 | 2 | 86.60 | 0.890 | +56.51% | -35.25% | 1.54 | 20 | continue | approaching_target |
| 4 | 6 | 86.60 | 0.890 | +56.51% | -35.25% | 1.54 | 20 | continue | approaching_target |
| 5 | 4 | 79.08 | 0.825 | +49.09% | -35.25% | 1.42 | 21 | continue | approaching_target |
| 6 | 1 | -19.62 | 0.529 | +6.04% | -59.41% | 1.04 | 24 | continue | high_drawdown |
| 7 | 7 | -100.00 | 0.070 | -46.52% | -72.41% | 0.74 | 25 | continue | high_drawdown |
| 8 | 8 | -100.00 | -0.692 | -45.16% | -59.30% | 0.59 | 10 | continue | high_drawdown |
| 9 | 9 | -100.00 | -20.000 | -88.94% | -100.00% | 0.55 | 17 | continue | ruined |
| 10 | 10 | -100.00 | -20.000 | -93.15% | -100.00% | 0.70 | 40 | continue | ruined |