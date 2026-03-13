# Leaderboard Builder - session 20260313_121720_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=31) - donchian(period=40) - atr(period=14) entry: - long: amplitude_hunter.score > 0.8 and close > donchian.upper - short: amplitude_hunter.score > 0.8 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.3 or cross_any(close, donchian.middle) risk: stop_atr_mult: 2.25 tp_atr_mult: 3.5 description: ATR stop-loss (2.25x) and take-profit (3.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.554
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 89.87 | 0.554 | +2493.97% | -32.19% | 1.70 | 3093 | continue | overtrading |
| 2 | 7 | 89.87 | 0.554 | +2493.97% | -32.19% | 1.70 | 3093 | continue | overtrading |
| 3 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 4 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 5 | 1 | -100.00 | 0.344 | -37.53% | -98.25% | 0.97 | 612 | continue | ruined |
| 6 | 4 | -100.00 | -20.000 | -534.11% | -100.00% | 0.76 | 1270 | continue | ruined |
| 7 | 5 | -100.00 | 0.344 | -37.53% | -98.25% | 0.97 | 612 | continue | ruined |
| 8 | 8 | -100.00 | -20.000 | -307.16% | -100.00% | 0.82 | 913 | continue | ruined |
| 9 | 9 | -100.00 | 0.344 | -37.53% | -98.25% | 0.97 | 612 | stop | ruined |