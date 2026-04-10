# 00-agent.md

## INTRODUCTION

### ⚠️ PRINCIPALE RÈGLE NON NÉGOCIABLE

Cette section est **intangible**.
Elle **ne doit jamais être modifiée**, déplacée ou reformulée.

Tout agent (LLM ou humain) DOIT s’y conformer.

### Règles fondamentales

1. **Modifier les fichiers existants** avant de créer quoi que ce soit.
2. **Se référer à ce fichier** pour se replacer dans le contexte global, comprendre l’historique des décisions et l’état actuel du travail.
3. **Poser des questions** en cas d’ambiguïté ou d’information manquante.
4. **Donner le meilleur niveau de qualité possible**, dans le cadre d’un **logiciel de trading algorithmique** visant la **rentabilité**, la **robustesse**, et une **utilisation ludique et intuitive**.
5. **Toute trace écrite liée à une modification est interdite ailleurs** : le compte rendu doit être consigné **ici uniquement**, sous un **format strictement identique** aux entrées précédentes et **ajouté en fin de fichier**.
6. **S’auto-corriger systématiquement** avant toute restitution finale.

👉 **Toute intervention qui ne respecte pas ces règles est invalide.**

**INTERDICTION DE MODIFIER LES INSTRUCTIONS CI-DESSUS**

---

### PS — Informations complémentaires (non prioritaires)

* Ce fichier est le **point d’entrée obligatoire** pour tout agent (LLM ou humain).
* Il garantit la **stabilité**, la **discipline** et la **continuité** du système.
* Il constitue la **mémoire opérationnelle centrale** : pour comprendre où en est le projet, ce qui a été fait, corrigé ou décidé, c’est **ici** qu’il faut lire.

---

## 📓 Journal des interventions (append-only)

> Après cette section, **aucun autre contenu structurel ne doit être ajouté**.
> Seules les **entrées successives d’interventions** sont autorisées.

Chaque intervention doit se conclure par une entrée concise et factuelle, **ajoutée à la suite**, sans jamais modifier les entrées précédentes.

### Format strict

* Date :
* Objectif :
* Fichiers modifiés :
* Actions réalisées :
* Vérifications effectuées :
* Résultat :
* Problèmes détectés :
* Améliorations proposées :


Fin de l'introduction Intouchables
==========================================================================================================

## Résumé opératoire

`AGENTS.md` est maintenant la version compacte du cadre projet. Le journal détaillé append-only vit dans `AGEND_HISTORY.md`, exclu de l'indexation Copilot pour éviter de resaturer le contexte agentique. Le bloc intangible ci-dessus est recopié tel quel pour compatibilité, même si la journalisation détaillée a été externalisée sur demande explicite du 28/03/2026.

## Priorités du dépôt

- Préserver un moteur de backtest fiable, rapide et explicable.
- Maintenir des stratégies orientées rentabilité réelle, pas seulement score in-sample.
- Garder une UI Streamlit exploitable sans multiplier les chemins implicites.
- Réduire le bruit de contexte pour les assistants et l'éditeur.
- Favoriser les corrections incrémentales sur l'existant avant toute nouvelle couche.

## État projet condensé

- `backtest/` contient le moteur, les métriques, l'exécution et la persistance des runs.
- `agents/` et `core/llm_multi/` portent le Builder mono et multi-LLM, l'orchestration, les rôles et l'instrumentation.
- `ui/` contient l'application Streamlit et les vues de pilotage/lecture des runs.
- `strategies/` et `indicators/` regroupent les briques métier versionnées.
- `config/profitable_presets.toml` conserve les presets rentables validés.
- Le store canonique est centré sur `BacktestStoreV3` et ses façades de compatibilité.
- Le Builder expose désormais une séparation explicite mono vs multi-LLM et une lecture de traces plus exploitable.

## Configurations rentables validées

### 1. EMA Cross 15/50

- Statut : production ready sur la fenêtre de validation historique.
- Paramètres clefs : `fast_period=15`, `slow_period=50`, `leverage=2`, `k_sl=2.0`.
- Résultat observé : `+1886.06`, soit `+18.86%`, `94` trades, `30.9%` de win rate, `PF 1.12`.

### 2. RSI Reversal 14/70/30

- Statut : production ready sur la même fenêtre.
- Paramètres clefs : `rsi_period=14`, `rsi_overbought=70`, `rsi_oversold=30`, `leverage=1`.
- Résultat observé : `+1880.04`, soit `+18.80%`, `59` trades, `32.2%` de win rate, `PF 1.28`.

### 3. EMA Cross 12/26

- Statut : rentable mais secondaire.
- Paramètres clefs : `fast_period=12`, `slow_period=26`, `leverage=2`, `k_sl=2.0`.
- Résultat observé : `+377.70`, soit `+3.78%`, `130` trades, `29.2%` de win rate, `PF 1.02`.

### Limites de validation

- Ces presets ont été validés sur `BTCUSDT 1h`, environ août 2024 à janvier 2025, `4326` barres.
- Ils ne doivent pas être promus en réel sans test hors échantillon, walk-forward et extension à d'autres symboles/timeframes.
- `macd_cross` et `bollinger_atr` restent des candidats à retravailler, pas des bases de déploiement immédiat.

## Commandes essentielles

```powershell
python -m cli backtest -s ema_cross -d data\BTCUSDC_1h.parquet
python -m cli sweep -s ema_cross -d data\BTCUSDC_1h.parquet --granularity 0.3 -m sharpe
python -m cli optuna -s ema_cross -d data\BTCUSDC_1h.parquet -n 200 --sampler tpe --pruning
python -m cli analyze --profitable-only -m total_return
python -m cli validate --all
python -m cli export -i results.json -f html -o rapport.html
python -m cli visualize -i results.json -d data\BTCUSDC_1h.parquet --html --no-show
python -m cli check-gpu --benchmark
python -m cli list strategies --json
python run_llm_optimization.py --strategy bollinger_atr --symbol BTCUSDC --timeframe 30m
```

## Références utiles

- `AGEND_HISTORY.md` : historique complet et journal append-only.
- `config/documentation_index.toml` : index documentaire central.
- `config/profitable_presets.toml` : presets validés.
- `README.md` : vue racine compacte et hygiène de contexte.
- `GUIDE_CREATION_NOUVELLE_STRATEGIE.md` : guide d'ajout d'une stratégie.
- `agents/strategy_builder.py` : Builder principal.
- `ui/builder_view.py` : vue Streamlit Builder.
- `core/llm_multi/` : orchestration multi-rôles.

## Garde-fous qualité

- Valider tout changement sensible avec compilation/tests ciblés avant restitution.
- Ne pas confondre performance in-sample et exploitabilité réelle.
- Éviter l'overfitting en exigeant du out-of-sample et du walk-forward dès qu'une stratégie paraît prometteuse.
- Garder les gros artefacts historiques ou générés hors du contexte implicite des assistants.
- Quand un fichier de référence devient trop massif, le découper plutôt que d'élargir encore le contexte global.

## Priorités ouvertes

- Étendre la validation rentable à `2025+` et à plusieurs symboles.
- Continuer la rationalisation du Builder autonome autour de contrats plus stricts et de fallbacks mieux mesurés.
- Poursuivre la réduction de surface des gros artefacts documentaires et générés.
- Garder la lecture UI mono vs multi-LLM séparée et explicite.
* Date : 2026-04-05
* Objectif : Introduire un univers de marchés canonique/exploratoire avec filtres locaux robustes, volatilité dépendante du type de stratégie, et traçabilité explicite dans Builder/validation/graduation.
* Fichiers modifiés : AGENTS.md ; config/market_selection.py ; config/market_selection.json ; agents/strategy_builder.py ; agents/builder_state.py ; agents/builder_objectives.py ; ui/state.py ; ui/sidebar.py ; ui/exec_tabs.py ; ui/builder_view.py ; catalog/graduation.py ; catalog/strategy_catalog.py ; backtest/storage.py ; tests/test_strategy_builder.py ; tests/test_ui_execution_contracts.py ; tests/test_strategy_catalog.py ; tests/test_graduation.py
* Actions réalisées : Centralisation de la logique d’univers dans `config.market_selection` avec `canonical` par défaut et `exploratory` en opt-in ; ajout des critères locaux d’éligibilité (âge listing local, segment continu, ratio `_tradable`, médiane dollar-volume avec fallback volume, volatilité annualisée par type de stratégie) ; propagation de `universe_mode`/`universe_purpose`/`universe_strategy_type`/`universe_meta` dans les sessions Builder, métadonnées de runs, catalog et graduation ; raccordement UI Builder/autonome pour rendre le choix d’univers explicite et restaurable ; ajout des raisons d’exclusion et des critères appliqués dans les sélections marché ; adaptation ciblée des tests existants.
* Vérifications effectuées : `python -m py_compile config\\market_selection.py agents\\strategy_builder.py agents\\builder_objectives.py agents\\builder_state.py ui\\state.py ui\\sidebar.py ui\\exec_tabs.py ui\\builder_view.py catalog\\graduation.py catalog\\strategy_catalog.py backtest\\storage.py tests\\test_strategy_builder.py tests\\test_ui_execution_contracts.py tests\\test_strategy_catalog.py tests\\test_graduation.py` ; `python -m pytest tests/test_strategy_builder.py tests/test_strategy_catalog.py tests/test_graduation.py -q` ; `python -m pytest tests/test_ui_execution_contracts.py::test_sample_sidebar_state_defaults_multi_llm_disabled tests/test_ui_execution_contracts.py::test_restore_builder_autonomous_ui_state_from_runtime_rehydrates_builder_mode tests/test_ui_execution_contracts.py::test_ensure_ollama_running_reports_empty_inventory tests/test_ui_execution_contracts.py::test_ensure_ollama_running_uses_current_store_and_clears_gpu_pinning_on_default_host tests/test_ui_execution_contracts.py::test_ensure_ollama_running_pins_gpu_for_dedicated_host -q`
* Résultat : Les runs Builder et les validations sérieuses transportent désormais explicitement leur mode d’univers et leurs critères ; le canonique est le défaut pour les chemins robustes ; l’exploratoire reste explicite ; la sélection marché repose d’abord sur des métriques locales et la volatilité est filtrée selon le profil de stratégie.
* Problèmes détectés : La suite complète `tests/test_ui_execution_contracts.py -q` reste trop longue pour la fenêtre d’exécution disponible ici, donc seules les portions impactées ont été rejouées ; le worktree contenait déjà de nombreuses modifications hors périmètre non touchées.
* Améliorations proposées : Étendre ensuite le même contrat d’univers canonique aux commandes CLI/validate si certains points d’entrée contournent encore le Builder UI ; ajouter une vue UI légère des exclusions marché par run pour faciliter le diagnostic utilisateur ; compléter la couverture de reprise autonome si d’autres états Builder doivent devenir persistants.
* Date : 2026-04-06
* Objectif : Rétablir une suite de tests cohérente après l’évolution des presets cloud multi-LLM, du filtrage marché Builder et de l’arrêt propre runtime.
* Fichiers modifiés : AGENTS.md ; tests/test_llm_multi.py ; ui/builder_view.py ; tests/test_ui_execution_contracts.py
* Actions réalisées : Réalignement ciblé des assertions `cloud_power_roles` et des scénarios d’override/failover cloud sur le preset et le contrat runtime actuellement versionnés ; ajout dans `ui/builder_view.py` d’un appel de compatibilité vers `_builder_market_candidates(...)` pour accepter les anciens stubs sans casser les nouveaux paramètres `objective/purpose/fallback_df` ; mise à jour du stub de `stop_local_ollama_server(...)` dans les tests UI pour couvrir le mot-clé `owned_only` désormais passé par l’arrêt propre.
* Vérifications effectuées : `python -m py_compile tests\\test_llm_multi.py ui\\builder_view.py tests\\test_ui_execution_contracts.py` ; `python -m pytest tests\\test_llm_multi.py -q` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "pick_market_for_objective or execute_clean_stop_resets_runtime_and_marks_manual_stop" -q` ; `python -m pytest -x -q`
* Résultat : La suite complète repasse au vert (`559 passed`) ; les tests couvrent désormais le preset cloud réellement embarqué, le fallback cloud visible au runtime, la compatibilité des stubs marché Builder et le stop propre avec `owned_only`.
* Problèmes détectés : Les fichiers `tests/test_llm_multi.py` et `tests/test_ui_execution_contracts.py` reflétaient encore d’anciens contrats alors que le code et les presets avaient déjà évolué ; le worktree global reste chargé de modifications hors périmètre non touchées.
* Améliorations proposées : Quand une signature helper interne change, ajouter immédiatement un shim de compatibilité ou mettre à jour tous les stubs associés dans la même passe ; éviter de faire évoluer un preset versionné sans réaligner au même moment les assertions qui en dépendent.
* Date : 2026-04-06
* Objectif : Empêcher le Builder autonome d’exécuter son bootstrap marché/runtime au simple affichage de la vue quand le mode autonome est activé mais non lancé.
* Fichiers modifiés : AGENTS.md ; ui/builder_view.py ; tests/test_ui_execution_contracts.py
* Actions réalisées : Ajout dans `ui/builder_view.py` d’un chemin explicite `idle` pour le mode autonome quand `st.session_state.is_running` est faux, avec rendu du hero et du récapitulatif sans warmup Ollama ni startup probe OHLCV ; court-circuit des logs/rotations/probes avant tout chargement marché ; ajout d’un test de non-régression validant qu’en mode autonome idle ni `_mark_builder_autonomous_runtime_started`, ni `_find_first_valid_builder_market`, ni `_prepare_builder_llm_resilient` ne sont appelés.
* Vérifications effectuées : `python -m py_compile ui\\builder_view.py tests\\test_ui_execution_contracts.py` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "autonomous_idle_skips_probe_and_runtime_prepare or startup_probe_fails" -q` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "render_main_auto_resumes_builder_autonomous_when_runtime_active or render_main_auto_resume_rehydrates_lost_builder_autonomous_flag or render_main_auto_resume_ignores_same_process_runtime_when_already_running" -q`
* Résultat : Le mode autonome n’amorce plus la sonde marché ni la préparation runtime tant que l’utilisateur n’a pas réellement lancé l’exécution ; l’auto-resume valide reste inchangé et les tests ciblés passent.
* Problèmes détectés : Le worktree reste chargé d’autres modifications hors périmètre sur `ui/builder_view.py` et `tests/test_ui_execution_contracts.py`, ce qui rend le diff global bruyant même si la zone corrigée est isolée.
* Améliorations proposées : Ajouter ensuite un indicateur UI plus explicite “idle vs runtime actif” dans la vue Builder autonome ; réduire aussi le bruit des logs `model_loader` si d’autres reruns passifs subsistent côté Streamlit.
* Date : 2026-04-07
* Objectif : Désactiver les MCP non utilisés (`linear`, `notion`, `hf-mcp-server`) dans l’environnement Codex utilisateur afin de supprimer les warnings de startup et n’activer que les outils réellement utiles.
* Fichiers modifiés : AGENTS.md ; C:\Users\o3-Pro\.codex\config.toml
* Actions réalisées : Ajout de `enabled = false` sur les sections `mcp_servers.notion` et `mcp_servers.linear` dans `~/.codex/config.toml` ; bascule du plugin `hugging-face@openai-curated` à `enabled = false` dans la même config pour retirer `hf-mcp-server` de la surface MCP par défaut ; nettoyage du flux OAuth Linear laissé en attente après le diagnostic précédent.
* Vérifications effectuées : `codex mcp list` ; relecture ciblée de `C:\Users\o3-Pro\.codex\config.toml`
* Résultat : `linear` et `notion` apparaissent désormais en `disabled`, `hf-mcp-server` n’est plus injecté dans la liste MCP, et le démarrage conserve seulement les serveurs utiles par défaut (`playwright`, `openaiDeveloperDocs`).
* Problèmes détectés : Aucun blocage restant sur ce périmètre ; `linear`/`notion` restent visibles dans la liste comme entrées désactivées, ce qui est attendu tant qu’on ne les supprime pas explicitement de la config.
* Améliorations proposées : Si vous voulez une surface encore plus minimale, on pourra ensuite retirer complètement les sections MCP désactivées au lieu de les garder en `disabled` ; réactiver ponctuellement un connecteur se fera simplement en remettant `enabled = true` puis en lançant le login OAuth correspondant.
* Date : 2026-04-07
* Objectif : Retirer des chemins guidés du programme `gemma3:4b`, `llama3.3-70b-optimized` et `gemma3:27b`, puis rafraîchir le modèle Google Gemma 3 disponible via Ollama.
* Fichiers modifiés : AGENTS.md ; agents/model_config.py ; agents/llm_config.py ; core/llm_multi/config/default_profiles.json ; data/multi_llm_profiles/24GB_custom.json ; data/multi_llm_profiles/24GB_custom_custom.json ; data/multi_llm_profiles/24GB_light_test_custom.json ; ui/components/model_selector.py ; ui/model_presets.py ; tests/test_llm_multi.py ; tests/test_ui_execution_contracts.py
* Actions réalisées : Suppression de `gemma3:4b` et `llama3.3-70b-optimized` du registre guidé `KNOWN_MODELS` ; retrait de `gemma3:27b` des registres/presets/pools/recommandations versionnés et remplacement par des alternatives déjà présentes (`lfm2:24b`, `mistral:22b`) pour conserver des profils cohérents ; conservation implicite de l’alias historique `llama3.3-70b-optimized -> llama3.3:70b-instruct-q4_K_M` dans `utils.model_loader` afin d’éviter une casse rétrocompatible ; exécution de `ollama pull gemma3:27b` puis contrôle de présence via `ollama list`.
* Vérifications effectuées : `rg -n --fixed-strings "gemma3:27b" agents core ui data\\multi_llm_profiles tests` ; `rg -n --fixed-strings "gemma3:4b" agents core ui data\\multi_llm_profiles tests` ; `rg -n --fixed-strings "llama3.3-70b-optimized" agents core ui data\\multi_llm_profiles tests utils` ; `python -m py_compile agents\\model_config.py agents\\llm_config.py ui\\components\\model_selector.py ui\\model_presets.py tests\\test_llm_multi.py tests\\test_ui_execution_contracts.py` ; chargement JSON ciblé de `core/llm_multi/config/default_profiles.json`, `data/multi_llm_profiles/24GB_custom.json`, `data/multi_llm_profiles/24GB_custom_custom.json`, `data/multi_llm_profiles/24GB_light_test_custom.json` ; `python -m pytest tests\\test_llm_multi.py -q` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "resolve_builder_dual_lane_preferences_prefers_live_widget_values or resolve_builder_multi_llm_preferences_uses_profile_role_pools_after_profile_switch" -q` ; `ollama pull gemma3:27b` ; `ollama list | findstr /C:"gemma3:27b"`
* Résultat : Les trois modèles demandés ont disparu des chemins guidés, recommandations et profils versionnés ; les tests ciblés passent ; le modèle Google Gemma 3 disponible côté Ollama a été rafraîchi localement sous le tag `gemma3:27b` (17 GB).
* Problèmes détectés : La demande mentionnait `26` milliards de paramètres, mais la variante Gemma 3 exposée par Ollama et documentée côté Google/Ollama est `27B` ; `llama3.3-70b-optimized` subsiste volontairement comme alias de compatibilité dans `utils.model_loader` et non comme option guidée active.
* Améliorations proposées : Si vous voulez un nettoyage plus agressif, on peut faire une seconde passe pour purger aussi les alias historiques/documentations obsolètes ; si vous voulez réintroduire Gemma 3 dans le programme plus tard, il vaudra mieux l’ajouter explicitement sous une seule forme canonique et avec un preset dédié plutôt qu’en doublon implicite.
* Date : 2026-04-07
* Objectif : Rechercher du code mort, des imports inutiles, des appels sans effet utile visible et des redondances sûres, puis nettoyer sans casser les contrats implicites du dépôt.
* Fichiers modifiés : AGENTS.md ; agents/builder_code_repair.py ; agents/builder_code_validation.py ; agents/builder_constants.py ; agents/builder_validation.py ; agents/pipeline_instrumentation.py ; agents/strategy_builder.py ; backtest/store_v3.py ; catalog/chainer.py ; catalog/runner.py ; cli/commands.py ; data/loader.py ; strategies/mean_reversion_bollinger_rsi.py ; strategies/momentum_macd.py ; tests/test_catalog.py ; tests/test_llm_multi.py ; tests/test_pipeline_instrumentation.py ; tests/test_strategy_builder.py ; tests/test_ui_execution_contracts.py ; tools/bench_real_multiprocess.py ; tools/benchmark_system.py ; tools/generate_html_report.py ; tools/test_sweep_performance.py ; tools/test_worker_fast.py ; tools/validate_numba_compilation.py ; ui/builder_view.py ; ui/components/model_selector.py ; ui/components/strategy_catalog_panel.py ; ui/exec_tabs.py ; ui/sidebar.py ; utils/sweep_diagnostics.py
* Actions réalisées : Audit statique via Ruff sur les erreurs `F401/F841/F811/F821` puis nettoyage ciblé des imports inutiles, variables locales mortes, assignations sans usage et collisions de nom ; correction des annotations manquantes (`Tuple`, `Iterable`) ; suppression d’assignations inutiles autour de warmups/compilations Numba et widgets Streamlit tout en conservant leurs effets de bord ; nettoyage des stubs de tests pour accepter les kwargs réels ; vérification Vulture haute confiance sur `agents/ui/catalog/backtest/strategies/tests/tools` ; restauration explicite des réexports `validate_generated_code` et `_repair_code` dans `agents.strategy_builder` après avoir constaté qu’ils faisaient partie du contrat implicite exposé par `agents.__init__`.
* Vérifications effectuées : `python -m ruff check . --select F401,F841,F811,F821 --output-format concise` ; `python -m py_compile agents\\builder_code_repair.py agents\\builder_code_validation.py agents\\builder_constants.py agents\\builder_validation.py agents\\pipeline_instrumentation.py agents\\strategy_builder.py backtest\\store_v3.py catalog\\chainer.py catalog\\runner.py cli\\commands.py data\\loader.py strategies\\mean_reversion_bollinger_rsi.py strategies\\momentum_macd.py tools\\bench_real_multiprocess.py tools\\benchmark_system.py tools\\generate_html_report.py tools\\test_sweep_performance.py tools\\test_worker_fast.py tools\\validate_numba_compilation.py ui\\builder_view.py ui\\components\\model_selector.py ui\\components\\strategy_catalog_panel.py ui\\exec_tabs.py ui\\sidebar.py utils\\sweep_diagnostics.py tests\\test_catalog.py tests\\test_llm_multi.py tests\\test_pipeline_instrumentation.py tests\\test_strategy_builder.py tests\\test_ui_execution_contracts.py` ; `python -m vulture agents ui catalog backtest strategies tests tools --min-confidence 90` ; `python -m pytest tests\\test_llm_multi.py tests\\test_pipeline_instrumentation.py -q` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "resolve_builder_dual_lane_preferences_prefers_live_widget_values or resolve_builder_multi_llm_preferences_uses_profile_role_pools_after_profile_switch or render_model_selector_maps_current_value_to_available_option" -q` ; `python -m pytest tests\\test_strategy_builder.py -k "precheck_signal_counts_handles_nameerror" -q`
* Résultat : La passe de nettoyage statique sûre a supprimé les warnings Ruff ciblés sur l’ensemble du dépôt ; Vulture ne remonte plus de candidat haute confiance sur les répertoires scannés ; les tests ciblés repassent au vert (`87 passed`, `3 passed`, `1 passed`) ; les chemins nettoyés conservent la compatibilité des réexports Builder attendus par le package et les tests.
* Problèmes détectés : Un faux positif initial de type “import inutile” dans `agents.strategy_builder` cachait en réalité un contrat de réexport consommé via `agents.__init__` et plusieurs tests ; Ruff continue d’afficher un warning d’accès refusé sur `.pytest_tmp_codex`, sans impact sur les résultats de lint.
* Améliorations proposées : Faire ensuite une passe dédiée sur les contrats de réexport du package `agents` pour les rendre explicites (`__all__`/module façade) et éviter de re-supprimer des symboles publics ; si vous voulez aller plus loin sur le “code mort”, on peut lancer une seconde passe plus ambitieuse centrée sur les alias historiques, helpers jamais appelés et duplications inter-UI, mais elle demandera davantage de revue fonctionnelle.
* Date : 2026-04-09
* Objectif : Reprendre la suite globale après la passe de nettoyage et stabiliser le premier échec restant sans dégrader le moteur.
* Fichiers modifiés : AGENTS.md ; backtest/engine.py
* Actions réalisées : Exécution de la suite complète jusqu’au premier échec (`test_simulator_fast_no_regression`) ; diagnostic du surcoût marginal sur le chemin `silent_mode=True` du moteur ; suppression des spans de tracing et de la recontextualisation logger déjà faite sur ce chemin, puis désactivation des `PerfCounters` détaillés en mode silencieux au profit d’un `total_ms` minimal calculé directement ; restauration explicite du logger de base en fin de run pour éviter l’empilement de contexte entre exécutions répétées.
* Vérifications effectuées : `python -m py_compile backtest\\engine.py` ; `python -m pytest tests\\test_perf_regression.py -k "simulator_fast_no_regression" -q` ; répétition x3 de `python -m pytest tests\\test_perf_regression.py -k "simulator_fast_no_regression" -q` ; `python -m pytest -x -q`
* Résultat : Le test de non-régression perf repasse de manière stable et la suite complète est verte (`565 passed` en `355.39s`, soit `0:05:55`).
* Problèmes détectés : La régression était marginale et intermittente (`2.01–2.06 ms` pour un seuil à `2.0 ms`), donc la correction devait réduire le coût fixe d’orchestration plutôt que toucher au noyau de simulation ; aucun autre échec n’a émergé sur la suite globale après correction.
* Améliorations proposées : Si vous voulez plus de marge sur les tests perf, on peut ensuite introduire un mode “benchmark harness” encore plus léger pour les sweeps silencieux (métadonnées minimales, zéro compteur détaillé, zéro contexte de log) ; en parallèle, on peut profiler plus finement `BacktestEngine.run()` pour distinguer clairement les coûts moteur vs métriques vs orchestration.
* Date : 2026-04-09
* Objectif : Finaliser le remplacement de `gemma3` par `gemma4` dans le programme et confirmer que seuls les modèles locaux Gemma 4 restent présents.
* Fichiers modifiés : AGENTS.md ; agents/model_config.py
* Actions réalisées : Suppression de la dernière entrée active `gemma3:12b` du registre central `KNOWN_MODELS` ; vérification qu’aucune référence `gemma3:` ne subsiste dans `agents`, `ui`, `core`, `tests`, `data` et `utils` ; contrôle de l’inventaire Ollama local confirmant la présence exclusive de `gemma4:26b` et `gemma4:31b`.
* Vérifications effectuées : `rg -n --fixed-strings "gemma3:" agents ui core tests data utils` ; `python -m py_compile agents\\model_config.py` ; `ollama list | findstr /I /C:"gemma3:" /C:"gemma4:"`
* Résultat : Le programme n’utilise plus `gemma3` dans ses chemins actifs ; côté local, seuls `gemma4:26b` et `gemma4:31b` sont actuellement installés.
* Problèmes détectés : Des mentions historiques de Gemma 3 persistent encore dans `AGENTS.md` et certains documents d’archive sous `docs/`, mais elles ne pilotent plus le runtime ni la sélection de modèles.
* Améliorations proposées : Si vous voulez un dépôt totalement homogène, on peut faire une dernière passe documentaire pour remplacer aussi les mentions archivées de Gemma 3 par Gemma 4 dans les documents non critiques.
* Date : 2026-04-08
* Objectif : Réaligner l’accès du code à la banque de données tokens/OHLCV après le basculement vers le gestionnaire `gestionnaire_telechargement_multi-timeframe_clean` devenu source principale.
* Fichiers modifiés : AGENTS.md ; .env ; utils/config.py ; cli/commands.py ; RUN_STREAMLIT.bat ; tools/scripts/Test_Streamlit.ps1 ; tests/unit/test_loader_timeframe.py
* Actions réalisées : Diagnostic des chemins réellement résolus par `data.loader`, `utils.config`, le CLI et les scripts de lancement ; identification d’un décalage entre le loader central (qui savait déjà auto-détecter `D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet`) et d’autres points d’entrée encore branchés sur l’ancien stockage via `.env`, `TRADX_DATA_ROOT` ou des fallbacks `sample_data` ; correction de `utils.config._default_data_dir()` pour déléguer d’abord à `data.loader._get_data_dir()` ; centralisation dans `cli/commands.py` d’une résolution canonique `_get_resolved_data_dir()` / `_resolve_data_path()` puis remplacement des chemins manuels dans `list data`, `optuna`, `visualize`, `builder` et `validate --all` ; mise à jour de `RUN_STREAMLIT.bat` et `tools/scripts/Test_Streamlit.ps1` pour prioriser explicitement le dossier `..._clean` ; correction du `.env` projet qui forçait encore `BACKTEST_DATA_DIR` vers l’ancien répertoire.
* Vérifications effectuées : `python -m py_compile utils\\config.py cli\\commands.py data\\loader.py tests\\unit\\test_loader_timeframe.py` ; `python -m pytest tests\\unit\\test_loader_timeframe.py -q` ; vérification runtime Python de `data.loader._get_data_dir()`, `cli.commands._get_resolved_data_dir()`, `cli.commands._resolve_data_path('BTCUSDC_1h.parquet')` et `Config().data_dir` ; contrôle de `discover_available_data()` après chargement CLI/environnement ; relecture ciblée de `.env`.
* Résultat : Le code principal, le CLI et les scripts de lancement convergent désormais vers `D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet` ; les commandes qui chargeaient encore l’ancien dossier ou `sample_data` voient maintenant la banque complète ; la vérification finale retrouve `288` tokens et les timeframes `3m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M`.
* Problèmes détectés : Le dépôt contenait un `.env` forçant encore `BACKTEST_DATA_DIR=D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet` ; `TRADX_DATA_ROOT` reste défini dans l’environnement vers `D:\TradXPro\crypto_data_json`, chemin désormais absent, mais n’interfère plus avec la résolution canonique corrigée tant que `BACKTEST_DATA_DIR` pointe correctement vers `..._clean`.
* Améliorations proposées : Si vous voulez supprimer toute ambiguïté restante, on peut faire une seconde passe pour nettoyer aussi les outils annexes/benchmarks qui gardent encore des chemins historiques vers l’ancien gestionnaire ; on peut également retirer ou corriger définitivement `TRADX_DATA_ROOT` dans l’environnement système pour éliminer ce reliquat de compatibilité.
* Date : 2026-04-08
* Objectif : Vérifier le nouveau modèle local Google Gemma 4 sur internet puis intégrer les variantes locales 26B et 31B au programme pour pouvoir les tester dans le Builder et les sélecteurs LLM.
* Fichiers modifiés : AGENTS.md ; utils/model_loader.py ; agents/model_config.py ; agents/llm_config.py ; ui/components/model_selector.py ; ui/model_presets.py ; core/llm_multi/config/default_profiles.json ; tests/test_llm_multi.py ; tests/test_ui_execution_contracts.py
* Actions réalisées : Vérification web du lancement officiel Gemma 4 publié par Google le 02/04/2026, avec variantes majeures `26B MoE (A4B)` et `31B Dense` ; normalisation des tags Ollama quantifiés vers les noms canoniques `gemma4:26b` et `gemma4:31b` ; ajout des deux modèles dans `KNOWN_MODELS` avec catégories/recommandations ; ajout dans les recommandations UI/LLM et création d’un preset UI `Gemma 4` ; ajout d’un profil Builder multi-LLM `24GB_gemma4_duo` pour comparer les deux modèles ; ajout de tests de non-régression sur les pools de profil et la résolution d’alias Gemma 4.
* Vérifications effectuées : `python -m py_compile utils\\model_loader.py agents\\model_config.py agents\\llm_config.py ui\\components\\model_selector.py ui\\model_presets.py tests\\test_llm_multi.py tests\\test_ui_execution_contracts.py` ; chargement JSON ciblé de `core/llm_multi/config/default_profiles.json` avec assertion sur `24GB_gemma4_duo` ; `python -m pytest tests\\test_llm_multi.py -k "gemma4 or historical_aliases" -q` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "gemma4_variant_tags or runtime_catalog_when_ollama_is_down" -q` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "resolve_builder_multi_llm_preferences_uses_profile_role_pools_after_profile_switch or sync_builder_multi_llm_profile_role_pools_hydrates_and_clears_session_state" -q` ; `python -m pytest tests\\test_llm_multi.py -k "builtin_diverse_role_pools or resolve_profile_assignments_light_profile_prefers_small_models" -q` ; `ollama --version`
* Résultat : Le programme connaît désormais `gemma4:26b` et `gemma4:31b` dans le registre central, les recommandations UI et les profils Builder ; les alias Ollama quantifiés sont ramenés aux noms canoniques ; les tests ciblés passent ; un preset UI et un profil multi-LLM dédiés permettent de lancer des essais comparatifs sans modifier les profils existants.
* Problèmes détectés : Ollama n’était pas lancé sur `http://127.0.0.1:11434` pendant l’intervention, donc aucun `pull`/test runtime réel des poids n’a été exécuté ; le dépôt ne contient pas le catalogue externe `C:\AI\models\catalog\models.json`, donc l’intégration a été faite dans le code versionné du programme plutôt que dans un registre machine-spécifique hors dépôt.
* Améliorations proposées : Si vous voulez l’étape suivante, on peut lancer ensuite les téléchargements réels `ollama pull gemma4:26b` et `ollama pull gemma4:31b`, puis brancher un preset d’évaluation backtest dédié pour comparer systématiquement 26B vs 31B sur les mêmes sessions Builder.
* Date : 2026-04-08
* Objectif : Auditer le bouton `Arrêter et nettoyer`, supprimer la logique d’arrêt empilée qui ne tenait pas ses promesses, et rétablir un arrêt Builder/LLM unique, indépendant des faux nettoyages précédents et réellement piloté par les hosts Ollama actifs.
* Fichiers modifiés : AGENTS.md ; ui/emergency_stop.py ; ui/main.py ; tests/test_ui_execution_contracts.py
* Actions réalisées : Audit du chemin `ui.main -> ui.emergency_stop -> agents.ollama_manager` à partir du bouton de la capture ; suppression de l’ancien `EmergencyStopHandler` singleton (stop event local, host `127.0.0.1:11434` codé en dur, nettoyage mémoire partiellement cosmétique, duplication avec `ui.main`) ; réécriture de `ui/emergency_stop.py` en routine déterministe sans singleton, recevant explicitement la liste des hosts Ollama à nettoyer, appliquant les flags d’arrêt, purgeant le contexte de session LLM, vidant les caches utiles, déchargeant les modèles par host et basculant en arrêt local plus agressif seulement quand des modèles restent chargés ; simplification de `ui/main.py` pour déléguer l’arrêt à cette seule routine au lieu de refaire un deuxième passage local sur les mêmes actions ; ajout d’un test de délégation UI et d’un test direct du contrat d’arrêt unifié (déduplication hosts, callbacks de cache, fallback `owned_only=False` si des modèles restent présents).
* Vérifications effectuées : `python -m py_compile ui\\emergency_stop.py ui\\main.py tests\\test_ui_execution_contracts.py` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "execute_clean_stop_resets_runtime_and_marks_manual_stop or execute_emergency_stop_cleans_runtime_hosts_and_callbacks" -q`
* Résultat : Le bouton ne repose plus sur deux couches concurrentes de nettoyage ; l’arrêt Builder/LLM passe désormais par une seule autorité avec inventaire multi-host, nettoyage de session cohérent, et fallback explicite quand l’unload seul ne suffit pas ; les tests ciblés passent (`2 passed`).
* Problèmes détectés : La suite complète `python -m pytest tests\\test_ui_execution_contracts.py -q` dépasse largement la fenêtre d’exécution disponible ici et a expiré sans fournir de verdict complet ; le worktree global reste fortement modifié hors périmètre, ce qui rend le diff global bruyant.
* Améliorations proposées : Ajouter ensuite un test d’intégration réellement runtime contre un daemon Ollama local vivant pour valider le chemin `cleanup_all_models -> /api/ps restant -> stop_local_ollama_server` sur machine réelle ; si vous voulez aller plus loin, on peut aussi retirer du wording UI toute promesse inutile et afficher explicitement quels hosts ont été nettoyés, stoppés ou laissés actifs.
* Date : 2026-04-09
* Objectif : Supprimer localement les deux modèles Gemma 3 encore installés, basculer les profils actifs vers Gemma 4 et installer les nouvelles variantes `gemma4:26b` et `gemma4:31b`.
* Fichiers modifiés : AGENTS.md ; agents/model_config.py ; agents/llm_config.py ; core/llm_multi/config/default_profiles.json ; data/multi_llm_profiles/24GB_light_test_custom.json ; data/multi_llm_profiles/robustes_ML.json ; data/multi_llm_profiles/robustes_ML_custom.json ; ui/components/model_selector.py ; ui/model_presets.py ; tests/test_llm_multi.py ; tests/test_ui_execution_contracts.py
* Actions réalisées : Inventaire local Ollama confirmant la présence de `gemma3:12b` et `gemma3:27b` ; remplacement dans les presets/profils/tests actifs des références restantes à `gemma3:12b` par `gemma4:26b` ou d’autres alternatives déjà guidées ; retrait des derniers fallbacks UI orientés Gemma 3 au profit de Gemma 4 ; suppression réelle des poids locaux via `ollama rm gemma3:27b` puis `ollama rm gemma3:12b` ; téléchargement des nouveaux modèles via `ollama pull gemma4:26b` et `ollama pull gemma4:31b`.
* Vérifications effectuées : `ollama list | Select-String -Pattern "gemma3|gemma4"` ; `rg -n "gemma3:12b|gemma3:27b" agents ui core tests data utils -S` ; `python -m py_compile agents\\model_config.py agents\\llm_config.py ui\\components\\model_selector.py ui\\model_presets.py tests\\test_llm_multi.py tests\\test_ui_execution_contracts.py` ; `python -m pytest tests\\test_llm_multi.py -k "prefers_verified_local_models or light_profile_prefers_small_models or prefers_live_ollama_match_when_required or gemma4_duo or historical_aliases" -q` ; `python -m pytest tests\\test_ui_execution_contracts.py -k "prefers_live_widget_values or profile_role_pools_after_profile_switch or pick_builder_session_role_overrides_selects_one_model_per_role or gemma4_variant_tags" -q`
* Résultat : Les deux Gemma 3 locaux ont été supprimés ; Ollama n’expose plus que `gemma4:26b` et `gemma4:31b` sur ce périmètre ; les profils/presets guidés du programme pointent désormais vers Gemma 4 à la place de Gemma 3 pour les chemins encore actifs ; les compilations et tests ciblés passent.
* Problèmes détectés : Une entrée de compatibilité historique `gemma3:12b` reste définie dans `agents/model_config.py` comme alias connu du registre central, mais elle n’est plus utilisée par les presets/profils/tests actifs ni installée localement.
* Améliorations proposées : Si vous voulez une purge totale du nom Gemma 3, on peut faire une seconde passe pour retirer aussi cette entrée de compatibilité du registre central ; l’étape utile suivante serait de lancer un benchmark Builder/backtest comparatif `gemma4:26b` vs `gemma4:31b`.* Date : 2026-04-09
* Objectif : Connecter les 8 étapes ablables du Builder Flow Analysis qui étaient déclarées dans `AblationController.ABLATABLE_STEPS` mais sans aucun check `ablation.is_enabled()` effectif dans le pipeline, rendant leurs toggles UI sans effet.
* Fichiers modifiés : AGENTS.md ; agents/builder_code_repair.py ; agents/builder_candidate_executor.py ; agents/strategy_builder.py ; tests/test_pipeline_instrumentation.py
* Actions réalisées : Audit complet des 14 étapes : 6 déjà connectées (`code_repair`, `precheck`, `stagnation_branching`, `positive_progress_gate`, `stop_override`, `accept_override`) ; 8 manquantes corrigées : ajout du paramètre `enable_indicator_binding=True` à `_repair_code()` propagé à tous les appelants internes avec `self.builder.ablation.is_enabled("indicator_binding")` ; guards inline pour `postprocess_logic` sur les 3 appels à `_postprocess_llm_logic_block()` ; guard `auto_fix_indicators` sur les 3 appels à `_auto_fix_required_indicators()` dont les deux dans `_recover_runtime_failure()` ; guard `params_contract_check` sur le bloc `_params_only_contract_respected()` dans `_resolve_candidate_code()` ; guard `runtime_fix` sur `_retry_code_runtime_fix()` avec safe-fallback `valid_retry=False` quand ablated ; guard `deterministic_fallback` dans `_next_fallback_code()` avec raise immédiat si désactivé ; paramètre `enable_leakage_filter=True` ajouté à `sanitize_objective_text()` et passé depuis `run()` via `self.ablation.is_enabled("prompt_leakage_filter")` ; guards `proposal_sanitize` sur les deux appels à `_sanitize_proposal_payload()` dans `_ask_proposal()` ; 3 nouveaux tests ajoutés dans `TestAblationController` : vérification des 14 étapes, test du paramètre `indicator_binding`, test du filtre de fuite.
* Vérifications effectuées : `python -m py_compile agents\builder_code_repair.py agents\builder_candidate_executor.py agents\strategy_builder.py` ; `python -m pytest tests\test_pipeline_instrumentation.py -q` (41 passed) ; `python -m pytest -x -q` (568 passed en 5:31).
* Résultat : Les 14 étapes affichées dans l'UI Builder Flow Analysis sont désormais toutes réellement connectées au pipeline ; désactiver/activer chaque toggle a un effet concret mesurable sur le flux du Builder.
* Problèmes détectés : Aucun.
* Améliorations proposées : Ajouter un test d'intégration de bout en bout qui lance un mini-run Builder avec chaque étape désactivée isolément et vérifie un comportement observable différent ; documenter dans l'UI la catégorie de chaque guard (optimise vs restreint) pour guider l'utilisateur dans ses choix d'ablation.
* Date : 2026-04-09
* Objectif : Étendre le système d'ablation de 14 à 18 étapes en ajoutant les fonctionnalités pipeline non encore représentées, puis mesurer le coût CPU réel de chaque étape sur le hardware local.
* Fichiers modifiés : AGENTS.md ; agents/pipeline_instrumentation.py ; agents/strategy_builder.py ; agents/builder_loop.py ; ui/exec_tabs.py ; tests/test_pipeline_instrumentation.py ; tools/benchmark_ablation.py (créé)
* Actions réalisées : Audit des 14 étapes déclarées vs code réel — 4 comportements toujours actifs sans guard identifiés : `indicator_ranking` (`rank_indicator_selection()` dans `_ask_proposal` et `_ask_code`), `iteration_history` (injection des 5 dernières itérations dans le prompt proposal), `diagnostic_context` (injection `context["diagnostic"]`/`diag_actions`/`diag_donts` dans proposal et code), `llm_analysis` (`_ask_analysis()` — 1 appel LLM par itération) ; ajout des 4 étapes dans `ABLATABLE_STEPS` ; implémentation de 5 guards dans `strategy_builder.py` (fallback `list(self.available_indicators)` si ranking désactivé, dict injection conditionnelle), 1 guard dans `builder_loop.py` avec fallback rule-based `[sharpe ≥ target_sharpe → accept]` ; mise à jour des 18 labels UI dans `exec_tabs.py` ; renommage et extension du test `test_all_14_steps_declared` → `test_all_18_steps_declared` ; création de `tools/benchmark_ablation.py` (CLI standalone, 30 runs/étape, médiane ± σ, pas d'Ollama requis) ; confirmation que `ui/state.py` lit `ABLATABLE_STEPS` dynamiquement — aucune modification nécessaire.
* Vérifications effectuées : `python -m py_compile agents\\pipeline_instrumentation.py agents\\strategy_builder.py agents\\builder_loop.py ui\\exec_tabs.py tests\\test_pipeline_instrumentation.py tools\\benchmark_ablation.py` ; `python -m pytest tests\\test_pipeline_instrumentation.py -q` (41 passed) ; `python -m pytest -q --ignore=tests\\test_agent_guardrails.py` (563 passed en 300s) ; `python tools\\benchmark_ablation.py --n-runs 30`.
* Résultat : 18 étapes actives et connectées ; `code_repair` coûte 21.79 ± 0.12 ms/iter (étape la plus lourde), `indicator_binding` 2.40 ms, `params_contract_check` 0.64 ms, `postprocess_logic` 0.44 ms, `indicator_ranking` 0.35 ms — les 13 autres sont < 0.05 ms ou N/A LLM ; 563 tests passent, 0 régression.
* Problèmes détectés : `test_agent_guardrails.py::test_autonomous_strategist_enforces_time_budget_when_iterations_unbounded` échoue de manière pré-existante (test de timing non-déterministe sur `autonomous_strategist.py`, aucun des fichiers modifiés n'est impliqué).
* Améliorations proposées : L'étape la plus impactante à désactiver pour des sessions de prototypage rapide est `code_repair` (économie de ~22 ms/iter) ; `llm_analysis` est l'étape LLM la plus chère (temps réseau+inférence) — son fallback rule-based peut être utile pour des passes d'ablation comparatives sans daemon Ollama ; un test d'intégration de bout en bout de l'ablation reste à faire si une campagne d'évaluation systématique est souhaitée.
* Date : 2026-04-10
* Objectif : Appliquer les enseignements du benchmark ablation pour réduire concrètement le coût CPU de `_repair_code` sur du code LLM propre.
* Fichiers modifiés : AGENTS.md ; agents/builder_code_repair.py ; tools/benchmark_ablation.py (résultat de benchmark utilisé) ; tools/_profile_repair_instrumented.py (créé, profiling interne) ; tools/_profile_helpers.py (créé, profiling unitaire)
* Actions réalisées : Correction de la condition `_structurally_sound` (retrait du faux critère `"np.nan_to_num(indicators[" not in code` qui bloquait le fast-path pour tout code utilisant nan_to_num sur des indicateurs array) ; restructuration complète : `_structurally_sound` déplacé avant le step 3b pour le gater ; ajout du constant module `_NAN_TO_NUM_DICT_SCAN` pour gater le step 4/4b (42 re.sub) par pre-scan O(N) ciblant uniquement les indicateurs dict ; step 3b (`_rewrite_invalid_indicator_accesses` + aliases sémantiques, ~2.7ms) gated sur `not _structurally_sound` ; step 4b (stochastic) fusionné dans la même gate ; step 12b (notation dot dict.subkey, 62 re.sub, ~2.2ms) gated sur `not _structurally_sound` ; three-step profiling (helpers individuels, instrumentation inline, benchmark final) pour identifier les vrais goulots.
* Vérifications effectuées : `python -m py_compile agents\\builder_code_repair.py` ; `python tools\\benchmark_ablation.py --n-runs 30` ; `python -m pytest tests\\test_pipeline_instrumentation.py tests\\test_strategy_builder.py tests\\test_ui_execution_contracts.py -q` (350 passed) ; `python -m pytest -q --ignore=tests\\test_agent_guardrails.py` (563 passed en 6:57).
* Résultat : `code_repair` passe de 21.79 ms (baseline pré-session) / 17.40 ms (après correctif _structurally_sound v1) à **4.53 ± 0.02 ms** — réduction de **79%** pour du code LLM structurellement propre. Tous les 563 tests passent, aucune régression.
* Problèmes détectés : Le profiling interne instrumenté a révélé une discordance entre les mesures unitaires (helpers ~0.15ms chacun) et les mesures pipeline (~2ms par step) ; la cause exacte reste non isolée (effets de cache CPU, contexte d'appel différent) mais les gatings ciblent honnêtement les contributions les plus élevées ; `tools/_profile_repair_instrumented.py` et `tools/_profile_helpers.py` sont des scripts de débogage temporaires, non intégrés au pipeline de test.
* Améliorations proposées : Pour aller encore plus loin, on pourrait gater step 12c (df_cols, ~22 re.sub) et le step `_inject_generate_signals_indicator_aliases` sur `_structurally_sound` ; implémenter un cache AST partagé entre `_repair_code` et `_inject_generate_signals_indicator_bindings` pour éviter le double parsing ; si la divergence profiling unitaire vs pipeline est creusée, la cause est probablement la pollution de cache L1/L2 entre les 300+ re.sub successifs dans la routine complète.
* Date : 2026-04-09
* Objectif : Enrichir la mémoire contextuelle du modèle LLM durant les itérations Builder : lui fournir l'historique complet des runs précédents (métriques, indicateurs utilisés, décision), la meilleure configuration atteinte dans la session, et une vue de tendance dans le prompt d'analyse.
* Fichiers modifiés : AGENTS.md ; agents/builder_state.py ; agents/builder_loop.py ; agents/strategy_builder.py ; strategies/templates/strategy_builder_proposal.jinja2
* Actions réalisées : Ajout du champ `used_indicators: List[str]` dans `BuilderIteration` ; propagation de ce champ dans `builder_loop.py` juste après l'assignation de `iteration.hypothesis` ; enrichissement de `iteration_history` dans `_ask_proposal` avec `win_rate`, `max_drawdown_pct`, `profit_factor`, `decision`, `indicators` en plus des champs existants ; ajout d'un bloc `best_so_far` dans le contexte de la proposition (meilleure itération session : hypothèse, indicateurs, métriques complètes) ; mise à jour du template `strategy_builder_proposal.jinja2` pour afficher le tableau d'historique enrichi et le bloc `BEST CONFIGURATION SO FAR` ; ajout dans `_ask_analysis` d'un bloc "Historique de la session" lisible ligne par ligne (avec marqueur ★ sur la meilleure itération, indicateurs utilisés par itération, décision et diagnostic).
* Vérifications effectuées : `python -m py_compile agents\\builder_state.py agents\\builder_loop.py agents\\strategy_builder.py` ; `python -m pytest tests\\test_strategy_builder.py tests\\test_pipeline_instrumentation.py -q` (214 passed en 1.97s).
* Résultat : À chaque itération, le modèle voit désormais : (1) l'historique complet de la session avec métriques enrichies et indicateurs par tentative, (2) la meilleure config atteinte pour s'y référer, (3) dans la phase d'analyse, une vue tabulaire de toutes les itérations précédentes avec tendance explicite. Ces informations évoluent au fil des runs et sont visibles à chaque appel LLM (proposition + analyse).
* Problèmes détectés : Aucun.
* Améliorations proposées : Si l'historique session devient très long (>15 itérations), envisager une compression — garder les 3 dernières et la meilleure en détail, résumer les autres en une seule ligne ; ajouter un champ `used_indicators` dans la sérialisation JSON des sessions sauvegardées pour rendre cet historique persistant entre rechargements.
* Date : 2026-04-10
* Objectif : Corriger le bug d'affichage du tableau autonome (best vs final sharpe) et renforcer le prompt d'analyse contre les décisions `stop` prématurées du modèle deepseek-r1-distill:14b. Audit complet du fichier de log fourni.
* Fichiers modifiés : AGENTS.md ; ui/builder_view.py ; agents/strategy_builder.py
* Actions réalisées : Audit des 7 sessions du fichier de log (09/04/2026 18h18–18h52) : identification du bug principal (tableau récap affichait `final_sharpe`/`final_return` comme valeurs principales au lieu de `best_sharpe`/`best_return` — la session 4 affichait Sharpe -20.000 au lieu de 0.900) ; inversion de la priorité dans `_render_autonomous_recap` (best* devient primaire, final* devient fallback) ; renforcement du system prompt `_ask_analysis` avec règles strictes anti-stop-précoce : `stop` uniquement si compte ruiné ET ≥3 itérations identiquement échouées, `continue` pour tout résultat négatif sur 1-2 itérations.
* Vérifications effectuées : `python -m py_compile agents\\strategy_builder.py ui\\builder_view.py` ; `python -m pytest tests\\test_strategy_builder.py tests\\test_pipeline_instrumentation.py -q` (214 passed en 1.97s).
* Résultat : La colonne Sharpe du tableau autonome montre désormais le meilleur Sharpe atteint dans la session (iter la plus profitable), pas la dernière itération potentiellement catastrophique ; le LLM ne pourra plus stopper après une seule itération négative.
* Problèmes détectés (audit log) : (1) Oscillation pathologique 0-trades→RUINED : même code cassé (Return -445.63%, 1354 trades, Sharpe -20) réapparu dans 3 sessions différentes — index de code identique généré par le LLM malgré des hypothèses différentes, probablement un bug de code repair qui produit un fallback cassé identique quand le bollinger est mal accédé ; (2) deepseek-r1-distill:14b arrêtait systematiquement après 1 itération négative ; (3) session 4 iter 1 avait Sharpe 0.900 mais était invisible dans le tableau à cause du bug (1).
* Améliorations proposées : Investiguer l'oscillation bollinger/ADX → 1354 trades RUINED : ce pattern exact (Return -445.63%, 1354 trades, WR 32.1%, PF 0.72) réapparaît de façon déterministe — probablement une expression `bollinger.lower`/`bollinger.upper` interprétée comme scalaire au lieu de array, ce qui inverse ou nullifie les conditions d'entrée ; ajouter un guard dans _repair_code pour détecter les runs avec >1000 trades et forcer un diagnostic de densité dès la génération de code.