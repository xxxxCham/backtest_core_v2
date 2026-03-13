# Leaderboard Builder - session 20260313_175807_fiche_strategie_v1_id_breakout_vwap_volu

Objective: FICHE_STRATEGIE v1 id: breakout_vwap_volume archetype: breakout_vwap_volume family: breakout timeframe: 15m symbol: BCHUSDC indicators: - vwap(period=20) - volume_oscillator(short_period=5, long_period=20) - atr(period=14) - standard_deviation(period=20) entry: - long: close > vwap.value and volume_oscillator > 0 and close > vwap.value + standard_deviation.value * 1.5 - short: close < vwap.value and volume_oscillator < 0 and close < vwap.value - standard_deviation.value * 1.5 exit: - condition: cross_any(close, vwap.value) risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: VWAP breakout strategy with volume confirmation and standard deviation bands for entry filtering
Strategy family: breakout.
Hypothesis: Captures institutional flow breakouts above/below VWAP with volume confirmation, using standard deviation bands to filter for significant moves while avoiding false breakouts during low-volume periods.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 4 | 3 | -100.00 | -20.000 | -245.98% | -100.00% | 0.64 | 623 | continue | ruined |
| 5 | 4 | -100.00 | -2.605 | -82.82% | -87.28% | 0.71 | 169 | continue | high_drawdown |
| 6 | 5 | -100.00 | -20.000 | -129.75% | -100.00% | 0.54 | 219 | continue | ruined |