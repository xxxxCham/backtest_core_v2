# Leaderboard Builder - session 20260313_084639_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=14) - donchian(period=35) - atr(period=14) entry: - long: amplitude_hunter.score > 0.8 and close > donchian.upper - short: amplitude_hunter.score > 0.8 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.35 or cross_any(close, donchian.middle) risk: stop_atr_mult: 2.0 tp_atr_mult: 3.5 description: ATR stop-loss (2.0x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 2 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |
| 3 | 1 | -100.00 | -20.000 | -463.77% | -100.00% | 0.68 | 1363 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -1796.25% | -100.00% | 0.57 | 5928 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -506.93% | -100.00% | 0.76 | 2080 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -463.77% | -100.00% | 0.68 | 1363 | continue | ruined |