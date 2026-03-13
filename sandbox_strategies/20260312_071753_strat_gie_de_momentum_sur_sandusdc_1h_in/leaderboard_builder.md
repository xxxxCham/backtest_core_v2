# Leaderboard Builder - session 20260312_071753_strat_gie_de_momentum_sur_sandusdc_1h_in

Objective: Stratégie de momentum sur SANDUSDC 1h. Indicateurs : EMA(20), EMA(50), RSI(14), ATR(14). Entrée longue lorsque EMA(20) > EMA(50) et RSI > 50. Sortie lorsque EMA(20) < EMA(50) ou RSI < 50. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Strategy family: momentum.
Hypothesis: Cette stratégie exploite les tendances haussières à court terme en identifiant un croisement d'EMAs avec confirmation RSI, tout en gérant le risque via un stop-loss dynamique basé sur l'ATR.
Constraints: Pas de lookahead : les décisions sont basées uniquement sur les données historiques disponibles; Utilisation exclusivement des indicateurs listés dans le catalogue
Status: running
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -100.00 | -2.313 | -66.34% | -76.35% | 0.77 | 273 | continue | high_drawdown |