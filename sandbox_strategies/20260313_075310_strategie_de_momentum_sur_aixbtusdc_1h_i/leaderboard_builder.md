# Leaderboard Builder - session 20260313_075310_strategie_de_momentum_sur_aixbtusdc_1h_i

Objective: Strategie de Momentum sur AIXBTUSDC 1h. Indicateurs : EMA(10), EMA(30), ATR. Calculer ROC = (close - close[12]) / close[12]. Entree short quand ROC < 0 et EMA(10) < EMA(30). Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: failed
Best Sharpe: 0.117
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 3 | 5 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 4 | 6 | -94.78 | 0.117 | -51.68% | -79.15% | 0.96 | 784 | stop | overtrading |
| 5 | 3 | -100.00 | -1.401 | -24.11% | -24.11% | 0.00 | 3 | continue | insufficient_trades |
| 6 | 4 | -100.00 | -20.000 | -97.57% | -100.00% | 0.81 | 187 | continue | ruined |