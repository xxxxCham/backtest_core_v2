# Leaderboard Builder - session 20260313_120334_style_momentum_sur_avaxusdc_15m_indicate

Objective: Style momentum sur AVAXUSDC 15m. Indicateurs : RSI + DONCHIAN + VOLUME_OSCILLATOR + ATR. Entrées : RSI croise au-dessus de 50 à l'intérieur des bandes de Donchian avec un pic de volume_oscillator. Sorties : RSI descend sous 50 ou fermeture en dessous de la bande inférieure de Donchian. Risk management : SL fixe à 1.5x ATR, TP dynamique selon les niveaux de Fibonacci. Filtre anti-faux-signaux : confirmation par un croisement de EMA 200 sur la période de. Mode_offbeat : combinaison RSI + Donchian + volume_oscillator rarement utilisée ensemble. Mode_inverse : test de logique inverse sur le filtre de volume_oscillator avec filtrage par regime de volatilité via ATR. Hypothèse : les mouvements de prix suivent une dynamique de "rupture contrôlée" lorsque les trois indicateurs sont alignés.
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 5 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 6 | 1 | -100.00 | -20.000 | -1189.21% | -100.00% | 0.53 | 3796 | continue | ruined |