# Leaderboard Builder - session 20260312_104603_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=9) - donchian(period=45) - atr(period=14) entry: - long: amplitude_hunter.score > 0.9 and close > donchian.upper - short: amplitude_hunter.score > 0.9 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.2 or cross_any(close, donchian.middle) risk: stop_atr_mult: 2.0 tp_atr_mult: 6.0 description: ATR stop-loss (2.0x) and take-profit (6.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -50.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 | -26.00 | 0.000 | +0.00% | 0.00% | 1.00 | 0 | continue | no_trades |
| 2 | 1 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 3 | 2 | -100.00 | -20.000 | -301.76% | -100.00% | 0.84 | 1383 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -2159.36% | -100.00% | 0.58 | 5677 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -861.83% | -100.00% | 0.61 | 1948 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -394.67% | -100.00% | 0.81 | 1562 | stop | ruined |