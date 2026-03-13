# Leaderboard Builder - session 20260313_182319_fiche_strategie_v1_id_breakout_vwap_cci

Objective: FICHE_STRATEGIE v1 id: breakout_vwap_cci_volume archetype: breakout_vwap_cci_volume family: breakout timeframe: 15m symbol: BCHUSDC indicators: - vwap(period=20) - cci(period=20) - volume_oscillator(short_period=5, long_period=20) - atr(period=14) entry: - long: close > vwap.value and cci > 100 and volume_oscillator > 0 - short: close < vwap.value and cci < -100 and volume_oscillator < 0 exit: - condition: cross_any(close, vwap.value) risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: VWAP breakout with CCI overbought/oversold confirmation and volume oscillator validation.
Strategy family: breakout.
Hypothesis: Captures strong institutional breakouts above/below VWAP using CCI extreme levels (>100/-100) to filter for momentum continuation rather than false breakouts, with volume oscillator confirming conviction. This addresses past failures by using CCI instead of standard deviation bands to identify stronger directional moves while maintaining volume validation.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -178.75% | -100.00% | 0.66 | 533 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -650.98% | -100.00% | 0.60 | 1918 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -571.30% | -100.00% | 0.56 | 1217 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -2268.92% | -100.00% | 0.34 | 6844 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -276.00% | -100.00% | 0.62 | 802 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -334.47% | -100.00% | 0.57 | 590 | stop | ruined |