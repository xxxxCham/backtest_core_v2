# Leaderboard Builder - session 20260312_134448_strategie_de_mean_reversion_sur_neousdc

Objective: Strategie de Mean-reversion sur NEOUSDC 1d. Indicateurs : RSI(14), ATR. Utiliser RSI court terme (params rsi_period=3) extreme bas (< 10) comme signal d'entree long, attente retour moyenne. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Status: running
Best Sharpe: -0.401
Best Continuous Score: -98.47

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -98.47 | -1.066 | -17.25% | -18.14% | 0.00 | 2 | continue | insufficient_trades |
| 2 | 1 | -100.00 | -0.401 | -46.97% | -59.71% | 0.32 | 6 | continue | high_drawdown |