# Leaderboard Builder - session 20260312_071021_strat_gie_de_momentum_sur_jtousdc_1h_ind

Objective: Stratégie de momentum sur JTOUSDC 1h. Indicateurs : EMA(20), EMA(50), RSI(14). Entrée longue lorsque EMA(20) > EMA(50) et RSI < 30. Sortie lorsque EMA(20) < EMA(50) ou RSI > 70. Stop-loss = 1.5x ATR, take-profit = 3.0x ATR.
Strategy family: momentum.
Hypothesis: Cette stratégie exploite un momentum haussier confirmé par une croisée des EMA avec un signal d'overbought/oversold RSI pour entrer en trend following avec une gestion de risque basée sur l'ATR.
Constraints: Pas de lookahead : les signaux doivent être générés à partir de données historiques disponibles uniquement.; Utilisation uniquement des indicateurs enregistrés : EMA, RSI, ATR.
Status: running
Best Sharpe: 0.161
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 3 | 4 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 4 | 1 | -53.50 | 0.161 | -7.66% | -59.40% | 0.96 | 73 | continue | high_drawdown |
| 5 | 5 | -87.19 | -5.000 | -10.00% | -25.00% | 0.50 | 3552 | continue | overtrading |