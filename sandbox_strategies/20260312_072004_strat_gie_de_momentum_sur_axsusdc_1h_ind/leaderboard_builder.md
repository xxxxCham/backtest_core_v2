# Leaderboard Builder - session 20260312_072004_strat_gie_de_momentum_sur_axsusdc_1h_ind

Objective: Stratégie de momentum sur AXSUSDC 1h. Indicateurs : EMA(20), EMA(50), RSI(14). Entrée longue lorsque EMA(20) > EMA(50) et RSI < 40. Sortie lorsque EMA(20) < EMA(50) ou RSI > 60. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Strategy family: momentum.
Hypothesis: Cette stratégie exploite les tendances haussières à court terme avec un filtrage RSI pour éviter les entrées dans des zones surachetées, en utilisant les EMA pour confirmer la direction du mouvement.
Constraints: Pas de lookahead : les signaux doivent être basés uniquement sur des données historiques disponibles au moment du trade.; Utilisation uniquement des indicateurs enregistrés dans le catalogue.
Status: running
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -334.93% | -100.00% | 0.64 | 1692 | continue | ruined |