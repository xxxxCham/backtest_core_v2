# Leaderboard Builder - session 20260312_105722_strategie_de_momentum_volatility_sur_tst

Objective: Strategie de Momentum / Volatility sur TSTUSDC 15m. Indicateurs : OBV, EMA(20), ATR. Entree long sur fort sursaut de volume (OBV acceleration) avec ATR en expansion et prix au-dessus de EMA(20). Stop-loss = 2.0x ATR, take-profit = 5.0x ATR.
Status: success
Best Sharpe: 2.678
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 100.00 | 2.678 | +221.48% | -14.95% | 1.93 | 149 | accept | target_reached |
| 2 | 2 | -3.04 | 0.496 | +16.91% | -59.28% | 1.03 | 246 | continue | high_drawdown |
| 3 | 1 | -100.00 | -20.000 | -1356.07% | -100.00% | 0.65 | 3918 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -130.08% | -100.00% | 0.71 | 126 | continue | ruined |