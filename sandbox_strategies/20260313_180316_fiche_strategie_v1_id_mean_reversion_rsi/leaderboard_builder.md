# Leaderboard Builder - session 20260313_180316_fiche_strategie_v1_id_mean_reversion_rsi

Objective: FICHE_STRATEGIE v1 id: mean_reversion_rsi_obv archetype: mean_reversion_rsi_obv family: mean_reversion timeframe: 1h symbol: MASKUSDC indicators: - rsi(period=14) - obv(period=20) - atr(period=14) entry: - long: rsi < 30 and obv > obv[1] - short: rsi > 70 and obv < obv[1] exit: - condition: cross_any(rsi, 50) or cross_any(obv, obv[1]) risk: stop_atr_mult: 2.0 tp_atr_mult: 3.0 description: ATR stop-loss (2.0x) and take-profit (3.0x)
Strategy family: mean_reversion.
Hypothesis: Exploits mean reversion by combining oversold/overbought RSI signals with OBV volume confirmation to filter false reversions, targeting price corrections with volume-supported momentum shifts.
Constraints: no_lookahead: true; only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -26.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 3 | 6 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | stop | no_trades |
| 4 | 5 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 5 | 1 | -100.00 | -20.000 | -173.46% | -100.00% | 0.75 | 476 | continue | ruined |
| 6 | 4 | -100.00 | -20.000 | -361.15% | -100.00% | 0.59 | 1320 | continue | ruined |