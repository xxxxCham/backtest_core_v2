# Leaderboard Builder - session 20260313_181637_fiche_strategie_v1_id_momentum_macd_vort

Objective: FICHE_STRATEGIE v1 id: momentum_macd_vortex_volume archetype: momentum_macd_vortex_volume family: momentum timeframe: 1h symbol: NEARUSDC indicators: - macd(fast_period=12, slow_period=26, signal_period=9) - vortex(period=14) - volume_oscillator(short_period=5, long_period=20) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and vortex.vi_plus > vortex.vi_minus and volume_oscillator > 0 - short: cross_down(macd.macd, macd.signal) and vortex.vi_minus > vortex.vi_plus and volume_oscillator < 0 exit: - condition: cross_down(macd.macd, macd.signal) for long positions or cross_up(macd.macd, macd.signal) for short positions risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: MACD trend-following with Vortex directional confirmation and volume oscillator validation
Strategy family: momentum.
Hypothesis: Combines MACD momentum signals with Vortex indicator directional confirmation to filter false breakouts, using volume oscillator to ensure conviction. This addresses past failures by adding directional trend confirmation beyond basic MACD crossovers while maintaining clear risk management.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 4 | 1 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 5 | 3 | -100.00 | -1.144 | -57.25% | -63.66% | 0.78 | 171 | continue | high_drawdown |
| 6 | 4 | -100.00 | -1.729 | -59.67% | -68.02% | 0.48 | 53 | continue | high_drawdown |