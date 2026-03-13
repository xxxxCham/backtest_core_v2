# Leaderboard Builder - session 20260313_093254_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=24) - donchian(period=40) - atr(period=14) entry: - long: amplitude_hunter.score > 0.6 and close > donchian.upper - short: amplitude_hunter.score > 0.6 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.4 or cross_any(close, donchian.middle) risk: stop_atr_mult: 2.25 tp_atr_mult: 6.0 description: ATR stop-loss (2.25x) and take-profit (6.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 2 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |
| 3 | 4 | -78.77 | -0.151 | -29.78% | -52.23% | 0.94 | 240 | continue | high_drawdown |
| 4 | 1 | -100.00 | -20.000 | -125.63% | -100.00% | 0.71 | 188 | continue | ruined |
| 5 | 3 | -100.00 | -20.000 | -316.70% | -100.00% | 0.68 | 948 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -125.63% | -100.00% | 0.71 | 188 | continue | ruined |