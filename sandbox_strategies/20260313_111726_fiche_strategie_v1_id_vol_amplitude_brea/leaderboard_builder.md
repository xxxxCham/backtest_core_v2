# Leaderboard Builder - session 20260313_111726_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=38) - donchian(period=15) - atr(period=14) entry: - long: amplitude_hunter.score > 0.65 and close > donchian.upper - short: amplitude_hunter.score > 0.65 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.4 or cross_any(close, donchian.middle) risk: stop_atr_mult: 2.5 tp_atr_mult: 3.0 description: ATR stop-loss (2.5x) and take-profit (3.0x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.000
Best Continuous Score: -25.36

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -25.36 | -0.250 | -10.74% | -30.24% | 0.96 | 282 | continue | needs_work |
| 2 | 5 | -25.36 | -0.250 | -10.74% | -30.24% | 0.96 | 282 | continue | needs_work |
| 3 | 2 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | continue | no_trades |
| 4 | 6 | -50.00 | 0.000 | +0.00% | 0.00% | 0.00 | 0 | stop | no_trades |
| 5 | 3 | -100.00 | -20.000 | -234.41% | -100.00% | 0.64 | 767 | continue | ruined |
| 6 | 4 | -100.00 | -20.000 | -168.54% | -100.00% | 0.70 | 592 | continue | ruined |