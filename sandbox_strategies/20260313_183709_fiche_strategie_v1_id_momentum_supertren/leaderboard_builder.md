# Leaderboard Builder - session 20260313_183709_fiche_strategie_v1_id_momentum_supertren

Objective: FICHE_STRATEGIE v1 id: momentum_supertrend_keltner_volume archetype: momentum_supertrend_keltner_volume family: momentum timeframe: 4h symbol: BCHUSDC indicators: - supertrend(atr_period=10, multiplier=3.0) - keltner(ema_period=20, atr_period=10, multiplier=1.5) - volume_oscillator(short_period=5, long_period=20) - atr(period=14) entry: - long: supertrend.direction == 1 and close > keltner.upper and volume_oscillator > 0.2 - short: supertrend.direction == -1 and close < keltner.lower and volume_oscillator < -0.2 exit: - condition: cross_any(close, keltner.middle) risk: stop_atr_mult: 1.5 tp_atr_mult: 3.0 description: Momentum breakout strategy using Supertrend for trend direction, Keltner Channel for volatility-based breakout confirmation, and volume oscillator for conviction validation.
Strategy family: momentum.
Hypothesis: Captures strong momentum breakouts by requiring alignment of trend direction (Supertrend), volatility expansion above/below Keltner Channel, and volume conviction. This addresses past failures by using multiple confirmation layers to filter false breakouts while maintaining clear risk management with ATR-based stops.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: running
Best Sharpe: 0.511
Best Continuous Score: -50.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 2 | 4 | -56.29 | 0.511 | -11.50% | -75.33% | 0.95 | 102 | continue | high_drawdown |
| 3 | 1 | -100.00 | -20.000 | -109.74% | -100.00% | 0.43 | 73 | continue | ruined |
| 4 | 2 | -100.00 | -1.466 | -56.36% | -73.60% | 0.83 | 188 | continue | high_drawdown |