# Leaderboard Builder - session 20260313_175431_fiche_strategie_v1_id_momentum_macd_adx

Objective: FICHE_STRATEGIE v1 id: momentum_macd_adx_volume archetype: momentum_macd_adx_volume family: momentum timeframe: 1h symbol: NEARUSDC indicators: - macd(fast_period=12, slow_period=26, signal_period=9) - adx(period=14) - volume_oscillator(short_period=5, long_period=20) - atr(period=14) entry: - long: cross_up(macd.macd, macd.signal) and adx.adx > 25 and volume_oscillator > 0 - short: cross_down(macd.macd, macd.signal) and adx.adx > 25 and volume_oscillator < 0 exit: - condition: cross_down(macd.macd, macd.signal) for long positions or cross_up(macd.macd, macd.signal) for short positions risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: MACD trend-following with ADX trend strength confirmation and volume oscillator for entry validation.
Strategy family: momentum.
Hypothesis: Exploits strong momentum trends by combining MACD crossovers with ADX trend strength filtering (>25) and volume oscillator confirmation to avoid false signals during low-volatility periods, targeting sustained directional moves.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: success
Best Sharpe: 1.143
Best Continuous Score: 100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | 100.00 | 1.143 | +144.97% | -27.53% | 1.86 | 25 | accept | target_reached |
| 2 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 4 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 5 | 4 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |