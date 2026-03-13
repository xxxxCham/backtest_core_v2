# Leaderboard Builder - session 20260312_085942_strategie_de_momentum_sur_uniusdc_30m_in

Objective: Strategie de Momentum sur UNIUSDC 30m. Indicateurs : EMA(20), ATR. Calculer la pente de EMA(20) via np.diff. Entree long quand la pente est positive et accelere. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: failed
Best Sharpe: 0.788
Best Continuous Score: 61.77

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 61.77 | 0.788 | +46.38% | -43.15% | 1.29 | 25 | continue | approaching_target |
| 2 | 4 | 41.79 | 0.670 | +31.60% | -46.02% | 1.23 | 25 | continue | approaching_target |
| 3 | 3 | 30.93 | 0.644 | +28.15% | -48.78% | 1.20 | 24 | continue | approaching_target |
| 4 | 2 | 4.93 | 0.581 | +16.91% | -48.58% | 1.10 | 19 | continue | approaching_target |
| 5 | 9 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 6 | 5 | -51.05 | 0.518 | -2.75% | -58.71% | 0.98 | 19 | continue | high_drawdown |
| 7 | 6 | -100.00 | -20.000 | -159.08% | -100.00% | 0.48 | 32 | continue | ruined |
| 8 | 7 | -100.00 | -1.516 | -82.11% | -85.82% | 0.41 | 11 | continue | high_drawdown |
| 9 | 8 | -100.00 | -0.130 | -56.11% | -73.09% | 0.65 | 37 | continue | high_drawdown |
| 10 | 10 | -100.00 | -20.000 | -194.26% | -100.00% | 0.42 | 33 | stop | ruined |