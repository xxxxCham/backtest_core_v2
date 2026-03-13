# Leaderboard Builder - session 20260313_181030_fiche_strategie_v1_id_momentum_supertren

Objective: FICHE_STRATEGIE v1 id: momentum_supertrend_adx_volume archetype: momentum_supertrend_adx_volume family: momentum timeframe: 4h symbol: BCHUSDC indicators: - supertrend(period=10, multiplier=3.0) - adx(period=14) - volume_oscillator(short_period=5, long_period=20) - atr(period=14) entry: - long: close > supertrend.up and adx.adx > 25 and volume_oscillator > 0 - short: close < supertrend.down and adx.adx > 25 and volume_oscillator < 0 exit: - condition: cross_any(close, supertrend.up) for long positions or cross_any(close, supertrend.down) for short positions risk: stop_atr_mult: 1.5 tp_atr_mult: 3.0 description: Supertrend trend-following with ADX strength confirmation and volume oscillator validation.
Strategy family: momentum.
Hypothesis: Captures sustained momentum trends by requiring price to break above/below the Supertrend line (indicating trend direction) with ADX > 25 confirming trend strength, plus volume oscillator alignment to filter low-conviction moves. This addresses past failures by using tighter risk management (1.5x ATR stop) and a clearer trend-following signal.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -100.00 | -20.000 | -3607.42% | -100.00% | 0.43 | 11640 | continue | ruined |
| 3 | 2 | -100.00 | -20.000 | -3920.62% | -100.00% | 0.38 | 11972 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -3600.46% | -100.00% | 0.43 | 11545 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -18503.19% | -100.00% | 0.19 | 61656 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -3111.44% | -100.00% | 0.38 | 9159 | stop | ruined |