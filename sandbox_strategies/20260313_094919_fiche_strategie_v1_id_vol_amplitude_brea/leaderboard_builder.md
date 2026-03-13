# Leaderboard Builder - session 20260313_094919_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=19) - donchian(period=25) - atr(period=14) entry: - long: amplitude_hunter.score > 0.75 and close > donchian.upper - short: amplitude_hunter.score > 0.75 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.15 or cross_any(close, donchian.middle) risk: stop_atr_mult: 1.75 tp_atr_mult: 4.5 description: ATR stop-loss (1.75x) and take-profit (4.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 2 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |
| 3 | 1 | -100.00 | -20.000 | -453.54% | -100.00% | 0.66 | 1236 | continue | ruined |
| 4 | 3 | -100.00 | -20.000 | -1691.56% | -100.00% | 0.55 | 5163 | continue | ruined |
| 5 | 4 | -100.00 | -20.000 | -553.89% | -100.00% | 0.72 | 2015 | continue | ruined |
| 6 | 5 | -100.00 | -20.000 | -453.54% | -100.00% | 0.66 | 1236 | continue | ruined |