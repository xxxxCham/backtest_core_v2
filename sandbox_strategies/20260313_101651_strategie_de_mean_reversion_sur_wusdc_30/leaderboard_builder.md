# Leaderboard Builder - session 20260313_101651_strategie_de_mean_reversion_sur_wusdc_30

Objective: Strategie de Mean-reversion sur WUSDC 30m. Indicateurs : Bollinger Bands(20,2), RSI(14), ATR. Entree long quand prix sous bande inferieure et RSI < 30. Stop-loss = 1.0x ATR, take-profit = 2.0x ATR.
Status: failed
Best Sharpe: 0.785
Best Continuous Score: 80.46

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | 80.46 | 0.785 | +39.28% | -27.04% | 1.17 | 186 | continue | approaching_target |
| 2 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 4 | -39.75 | -0.433 | -5.37% | -11.83% | 0.73 | 23 | continue | losing_per_trade |
| 4 | 8 | -40.20 | -0.450 | -5.84% | -13.45% | 0.73 | 26 | continue | losing_per_trade |
| 5 | 3 | -86.46 | -0.460 | -32.72% | -49.56% | 0.84 | 193 | continue | wrong_direction |
| 6 | 6 | -86.46 | -0.460 | -32.72% | -49.56% | 0.84 | 193 | continue | wrong_direction |
| 7 | 9 | -86.46 | -0.460 | -32.72% | -49.56% | 0.84 | 193 | stop | wrong_direction |
| 8 | 7 | -92.57 | -1.242 | -24.20% | -25.48% | 0.53 | 42 | continue | wrong_direction |
| 9 | 1 | -100.00 | -20.000 | -148.06% | -100.00% | 0.79 | 637 | continue | ruined |