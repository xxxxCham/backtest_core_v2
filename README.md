# Backtest Core V2

Moteur de backtest multi-LLM avec acceleration GPU pour strategies de trading algorithmique.

## Historique

- **V1** : `backtest_core` — moteur original (depot archive).
- **V2** : `backtest_core_v2` — refonte avec orchestration multi-LLM, acceleration GPU, UI Streamlit et catalogue de strategies.

## Docs Essentielles (Conservees En Racine)

- `AGENTS.md` : regles, historique, journal de maintenance.
- `GUIDE_CREATION_NOUVELLE_STRATEGIE.md` : guide principal pour ajouter une strategie.

## Exemples Legers Versionnes

- `examples/README.md` : point d'entree des exemples versionnes.
- `examples/end_to_end/README.md` : mini parcours de bout en bout avec OHLCV, resultats natifs, layout v3 et manifest legacy.
- `data/sample_data/generate_sample.py` : regeneration des petits CSV d'exemple commits dans `examples/end_to_end/data`.

## Docs Techniques Completes

La documentation technique detaillee est centralisee sous `docs/markdowns/`.

Point d entree unique pour les agents (LLM ou humains).
Lire AGENTS.md en premier pour les regles et le journal des modifications.

- [AGENTS.md](AGENTS.md)

## Arborescence du projet (auto)
Ce bloc est regenere par `python tools/update_readme_tree.py`.
d:\[
1. `metrics_types.py`
2. `profile_simple.py`
3. `profile_sweep.py`
4. `test_cpu_only_mode.py`
5. `agents\analyst.py`
6. `agents\autonomous_strategist.py`
7. `agents\backtest_executor.py`
8. `agents\base_agent.py`
9. `agents\builder_constants.py`
10. `agents\builder_diagnostics.py`
11. `agents\builder_objectives.py`
12. `agents\builder_validation.py`
13. `agents\critic.py`
14. `agents\indicator_context.py`
15. `agents\integration.py`
16. `agents\llm_client.py`
17. `agents\llm_config.py`
18. `agents\model_config.py`
19. `agents\ollama_manager.py`
20. `agents\orchestration_logger.py`
21. `agents\orchestrator.py`
22. `agents\state_machine.py`
23. `agents\strategist.py`
24. `agents\strategy_builder.py`
25. `agents\thought_stream.py`
26. `agents\validator.py`
27. `agents\__init__.py`
28. `agents\handlers\analyze_handler.py`
29. `agents\handlers\critique_handler.py`
30. `agents\handlers\init_handler.py`
31. `agents\handlers\iterate_handler.py`
32. `agents\handlers\propose_handler.py`
33. `agents\handlers\report_handler.py`
34. `agents\handlers\validate_handler.py`
35. `agents\handlers\__init__.py`
36. `backtest\config_storage.py`
37. `backtest\engine.py`
38. `backtest\errors.py`
39. `backtest\execution.py`
40. `backtest\execution_fast.py`
41. `backtest\facade.py`
42. `backtest\metrics_tier_s.py`
43. `backtest\monte_carlo.py`
44. `backtest\optuna_optimizer.py`
45. `backtest\pareto.py`
46. `backtest\performance.py`
47. `backtest\performance_numba.py`
48. `backtest\report_generator.py`
49. `backtest\results_organizer.py`
50. `backtest\result_store.py`
51. `backtest\returns_safe.py`
52. `backtest\simulator.py`
53. `backtest\simulator_fast.py`
54. `backtest\storage.py`
55. `backtest\sweep.py`
56. `backtest\sweep_numba.py`
57. `backtest\trade_analytics.py`
58. `backtest\validation.py`
59. `backtest\walk_forward.py`
60. `backtest\warmup.py`
61. `backtest\worker.py`
62. `backtest\__init__.py`
63. `catalog\builder_export.py`
64. `catalog\chainer.py`
65. `catalog\fingerprint.py`
66. `catalog\gating.py`
67. `catalog\models.py`
68. `catalog\ranges_loader.py`
69. `catalog\runner.py`
70. `catalog\sanity.py`
71. `catalog\__init__.py`
72. `cli\commands.py`
73. `cli\formatters.py`
74. `cli\report_generator.py`
75. `cli\sweep_executor.py`
76. `cli\validators.py`
77. `cli\__init__.py`
78. `cli\__main__.py`
79. `data\config.py`
80. `data\indicator_bank.py`
81. `data\loader.py`
82. `data\__init__.py`
83. `data\sample_data\generate_sample.py`
84. `examples\example_trade_analytics.py`
85. `indicators\adx.py`
86. `indicators\amplitude_hunter.py`
87. `indicators\aroon.py`
88. `indicators\atr.py`
89. `indicators\bollinger.py`
90. `indicators\cci.py`
91. `indicators\donchian.py`
92. `indicators\ema.py`
93. `indicators\fear_greed.py`
94. `indicators\fibonacci.py`
95. `indicators\filters.py`
96. `indicators\fva.py`
97. `indicators\fvg.py`
98. `indicators\ichimoku.py`
99. `indicators\keltner.py`
100. `indicators\macd.py`
101. `indicators\markov_switching.py`
102. `indicators\mfi.py`
103. `indicators\momentum.py`
104. `indicators\obv.py`
105. `indicators\onchain_smoothing.py`
106. `indicators\pivot_points.py`
107. `indicators\pi_cycle.py`
108. `indicators\psar.py`
109. `indicators\registry.py`
110. `indicators\roc.py`
111. `indicators\rsi.py`
112. `indicators\scoring.py`
113. `indicators\smart_legs.py`
114. `indicators\standard_deviation.py`
115. `indicators\stochastic.py`
116. `indicators\stoch_rsi.py`
117. `indicators\supertrend.py`
118. `indicators\swing.py`
119. `indicators\volume_oscillator.py`
120. `indicators\vortex.py`
121. `indicators\vwap.py`
122. `indicators\williams_r.py`
123. `indicators\__init__.py`
124. `labs\lab_launcher.py`
125. `labs\analysis\analyze_bollinger_atr_results.py`
126. `labs\analysis\analyze_code_health.py`
127. `labs\analysis\analyze_trade6.py`
128. `labs\analysis\analyze_winning_conditions.py`
129. `labs\analysis\detailed_bollinger_analysis.py`
130. `labs\debug\diagnostic_sweep_blocked.py`
131. `labs\debug\fix_streamlit_config.py`
132. `labs\debug\reproduce_macd_inf.py`
133. `labs\optimization\bollinger_atr_optimized_ranges.py`
134. `labs\optimization\bollinger_atr_theory_ranges.py`
135. `labs\optimization\profile_backtest.py`
136. `labs\optimization\quick_ranges_test.py`
137. `labs\visualization\parameter_heatmap.py`
138. `performance\benchmark.py`
139. `performance\device_backend.py`
140. `performance\hybrid_compute.py`
141. `performance\memory.py`
142. `performance\monitor.py`
143. `performance\parallel.py`
144. `performance\profiler.py`
145. `performance\__init__.py`
3556. `sandbox_strategies\20260221_132346_fiche_strategie_v1_id_breakout_donchian\strategy_v3.py`
3557. `strategies\base.py`
3558. `strategies\bollinger_atr.py`
3559. `strategies\bollinger_atr_v2.py`
3560. `strategies\bollinger_atr_v3.py`
3561. `strategies\bollinger_best_longe_3i.py`
3562. `strategies\bollinger_best_short_3i.py`
3563. `strategies\config.py`
3564. `strategies\ema_cross.py`
3565. `strategies\fvg_strategy.py`
3566. `strategies\indicators_mapping.py`
3567. `strategies\macd_cross.py`
3568. `strategies\rsi_reversal.py`
3569. `strategies\scalping_bollinger_vwap_atr.py`
3570. `strategies\scalp_ema_bb_rsi_labs.py`
3571. `strategies\__init__.py`
3572. `tests\analyze.py`
3573. `tests\benchmark_detailed.py`
3574. `tests\benchmark_hybrid.py`
3575. `tests\diagnose_numba_crash.py`
3576. `tests\fix_streamlit_config.py`
3577. `tests\metrics_types.py`
3578. `tests\test_backend_cpu_only.py`
3579. `tests\test_catalog.py`
3580. `tests\test_perf_regression.py`
3581. `tests\test_result_store_v2.py`
3582. `tests\test_strategy_builder.py`
3583. `tests\test_walk_forward.py`
3584. `tests\verify_ui_imports.py`
3585. `tests\unit\test_param_normalization.py`
3586. `tools\benchmark_system.py`
3587. `tools\bench_numba_prange.py`
3588. `tools\bench_real_multiprocess.py`
3589. `tools\bench_sweep_fast.py`
3590. `tools\test_worker_fast.py`
3591. `tools\validate_cpu_only.py`
3592. `ui\app.py`
3593. `ui\builder_view.py`
3594. `ui\cache_integration.py`
3595. `ui\cache_manager.py`
3596. `ui\config_form.py`
3597. `ui\constants.py`
3598. `ui\context.py`
3599. `ui\deep_trace_viewer.py`
3600. `ui\emergency_stop.py`
3601. `ui\helpers.py`
3602. `ui\indicators_panel.py`
3603. `ui\llm_handlers.py`
3604. `ui\log_taps.py`
3605. `ui\main.py`
3606. `ui\main_with_form.py`
3607. `ui\model_presets.py`
3608. `ui\orchestration_viewer.py`
3609. `ui\range_editor.py`
3610. `ui\results.py`
3611. `ui\results_hub.py`
3612. `ui\sidebar.py`
3613. `ui\state.py`
3614. `ui\validation_integration.py`
3615. `ui\worker_utils.py`
3616. `ui\__init__.py`
3617. `ui\components\agent_timeline.py`
3618. `ui\components\charts.py`
3619. `ui\components\diagram_factory.py`
3620. `ui\components\model_selector.py`
3621. `ui\components\monitor.py`
3622. `ui\components\sweep_monitor.py`
3623. `ui\components\validation_viewer.py`
3624. `ui\components\__init__.py`
3625. `ui\components\archive\indicator_explorer.py`
3626. `ui\components\archive\sweep_monitor.py`
3627. `ui\components\archive\themes.py`
3628. `ui\components\archive\thinking_viewer.py`
3629. `ui\components\archive\validation_viewer.py`
3630. `ui\pages\range_editor_page.py`
3631. `ui\theme\colors.py`
3632. `ui\theme\plotly_config.py`
3633. `ui\theme\__init__.py`
3634. `utils\backend_config.py`
3635. `utils\checkpoint.py`
3636. `utils\circuit_breaker.py`
3637. `utils\config.py`
3638. `utils\config_validator.py`
3639. `utils\data.py`
3640. `utils\diagnose_sweep_activity.py`
3641. `utils\error_recovery.py`
3642. `utils\health.py`
3643. `utils\indicator_ranges.py`
3644. `utils\llm_memory.py`
3645. `utils\log.py`
3646. `utils\memory.py`
3647. `utils\model_loader.py`
3648. `utils\observability.py`
3649. `utils\parameters.py`
3650. `utils\preset_validation.py`
3651. `utils\range_manager.py`
3652. `utils\run_tracker.py`
3653. `utils\session_param_tracker.py`
3654. `utils\session_ranges_tracker.py`
3655. `utils\sweep_diagnostics.py`
3656. `utils\template.py`
3657. `utils\version.py`
3658. `utils\visualization.py`
3659. `utils\__init__.py`](..)
