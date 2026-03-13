# Leaderboard Builder - session 20260307_075005_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=21) - donchian(period=15) - atr(period=14) entry: - long: amplitude_hunter.score > 0.7 and close > donchian.upper - short: amplitude_hunter.score > 0.7 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.1 or cross_any(close, donchian.middle) risk: stop_atr_mult: 1.5 tp_atr_mult: 4.5 description: ATR stop-loss (1.5x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: success
Best Sharpe: -inf
Best Continuous Score: -inf

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 100.00 | 1.901 | +192.91% | -32.76% | 1.23 | 560 | accept | target_reached |