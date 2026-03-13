# Leaderboard Builder - session 20260312_124740_fiche_strategie_v1_id_vol_amplitude_brea

Objective: FICHE_STRATEGIE v1 id: vol_amplitude_breakout archetype: vol_amplitude_breakout family: volatility timeframe: side: both indicators: - amplitude_hunter(period=46) - donchian(period=30) - atr(period=14) entry: - long: amplitude_hunter.score > 0.55 and close > donchian.upper - short: amplitude_hunter.score > 0.55 and close < donchian.lower exit: - condition: amplitude_hunter.score < 0.4 or cross_any(close, donchian.middle) risk: stop_atr_mult: 2.5 tp_atr_mult: 2.5 description: ATR stop-loss (2.5x) and take-profit (2.5x) constraints: - no_lookahead: true - only_registry_indicators: true
Status: failed
Best Sharpe: 0.673
Best Continuous Score: 20.62

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 37.94 | 0.546 | +48.68% | -54.68% | 1.06 | 346 | continue | high_drawdown |
| 2 | 1 | 20.62 | 0.673 | +53.72% | -78.66% | 1.05 | 500 | continue | high_drawdown |
| 3 | 8 | 20.62 | 0.673 | +53.72% | -78.66% | 1.05 | 500 | continue | high_drawdown |
| 4 | 9 | -51.80 | 0.335 | -12.40% | -65.74% | 0.98 | 289 | stop | high_drawdown |
| 5 | 5 | -78.15 | 0.372 | -30.03% | -76.06% | 0.96 | 291 | continue | high_drawdown |
| 6 | 2 | -100.00 | -20.000 | +48.25% | -100.00% | 1.04 | 618 | continue | ruined |
| 7 | 3 | -100.00 | -20.000 | -365.26% | -100.00% | 0.80 | 1233 | continue | ruined |
| 8 | 4 | -100.00 | -20.000 | +64.64% | -100.00% | 1.05 | 620 | continue | ruined |
| 9 | 7 | -100.00 | -20.000 | +48.25% | -100.00% | 1.04 | 618 | continue | ruined |