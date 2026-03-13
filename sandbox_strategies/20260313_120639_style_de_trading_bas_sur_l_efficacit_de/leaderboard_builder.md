# Leaderboard Builder - session 20260313_120639_style_de_trading_bas_sur_l_efficacit_de

Objective: Style de trading basé sur l'efficacité de volatilité sur NEARUSDC 15m. Indicateurs : ADX + KELTNER + VOLUME_OSCILLATOR + ATR. Entrées : lorsque le volume_oscillator croise au-dessus de son niveau moyen tandis que l'adx dépasse 25 et que le prix sort de la bande de Keltner. Sorties : lorsque le prix touche le niveau supérieur de Keltner ou que le volume_oscillator descend sous sa moyenne. Risk management : SL fixé à la distance ATR la plus récente, TP ajusté dynamiquement selon le niveau de volatilité actuelle avec une asymétrie long/short basée sur le filtre anti-faux-signaux.
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 2 | 1 | -100.00 | -20.000 | -406.83% | -100.00% | 0.65 | 1193 | continue | ruined |
| 3 | 2 | -100.00 | -20.000 | -257.58% | -100.00% | 0.70 | 877 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -237.60% | -100.00% | 0.69 | 802 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -237.60% | -100.00% | 0.69 | 802 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -378.26% | -100.00% | 0.68 | 1220 | continue | ruined |