# Leaderboard Builder - session 20260313_182943_fiche_strategie_v1_id_mean_reversion_rsi

Objective: FICHE_STRATEGIE v1 id: mean_reversion_rsi_obv_ema archetype: mean_reversion_rsi_obv_ema family: mean_reversion timeframe: 1h symbol: NEARUSDC indicators: - rsi(period=14) - obv(period=20) - ema(period=50) - atr(period=14) entry: - long: rsi < 30 and obv > obv[1] and close > ema.value - short: rsi > 70 and obv < obv[1] and close < ema.value exit: - condition: cross_any(rsi, 50) or cross_any(close, ema.value) risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: Mean reversion strategy using oversold/overbought RSI with OBV volume confirmation and EMA trend filter to avoid counter-trend trades
Strategy family: mean_reversion.
Hypothesis: Combines RSI extremes with OBV momentum and EMA trend confirmation to identify high-probability mean reversion opportunities while filtering false signals in strong trending markets, addressing previous failures by adding trend context
Constraints: no_lookahead: true; only_registry_indicators: true
Status: failed
Best Sharpe: 1.250
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 5 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 3 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 4 | 4 | -97.57 | -0.469 | -25.33% | -30.12% | 0.00 | 1 | continue | insufficient_trades |
| 5 | 2 | -100.00 | -0.499 | -40.38% | -56.22% | 0.41 | 4 | continue | insufficient_trades |
| 6 | 6 | -100.00 | 1.250 | -89.64% | -99.49% | 0.00 | 4 | stop | insufficient_trades |