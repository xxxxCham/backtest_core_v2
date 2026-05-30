# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Backtest Core V2 — moteur de backtest de trading algorithmique avec accélération
Numba/GPU et génération de stratégies pilotée par LLM (Ollama). Python ≥3.10,
Windows (PowerShell 7+). Réponses et code en français.

## Commands

```powershell
# Application Streamlit (point d'entrée unique, gère ports/caches/processus orphelins)
.\RUN_STREAMLIT.bat            # ajouter --clean / --clean-numba / --clean-all après MAJ sources
streamlit run ui/app.py        # lancement direct (sans le wrapper)

# CLI — toutes les commandes passent par `python -m cli <command>`
python -m cli list strategies                  # ou: indicators | data | presets  (+ --json)
python -m cli backtest -s ema_cross -d data/BTCUSDC_1h.parquet --capital 50000 --fees-bps 5
python -m cli sweep -s ema_cross -d data/BTCUSDC_1h.parquet --granularity 0.3 -m sharpe --parallel 8 --top 5
python -m cli optuna -s ema_cross -d data/BTCUSDC_1h.parquet -n 200 --sampler tpe --pruning
python -m cli validate --all
python -m cli check-gpu --benchmark
# autres sous-commandes: info, export, visualize, benchmark, llm-optimize, grid-backtest, analyze, cycle, builder, catalog

# Tests (pytest configuré dans pyproject.toml, testpaths=tests, basetemp=.pytest_tmp)
python -m pytest                               # toute la suite
python -m pytest tests/test_catalog.py         # un fichier
python -m pytest tests/test_graduation.py -k "audit"   # un sous-ensemble par mot-clé
python -m pytest -q tests/test_catalog.py::test_xxx    # un test unique

# Lint / format (line-length 120 partout)
ruff check .          # select E,F,W,I ; ignore E501/E402/F401
black .
isort .
mypy .                # ignore_missing_imports=true
```

## Architecture

Pipeline de backtest : **charger données → calculer indicateurs → générer signaux
→ simuler trades → métriques → résultat**. Les couches principales :

- **`backtest/`** — cœur du moteur.
  - `engine.py` : `BacktestEngine`, orchestration du pipeline, produit `RunResult`.
  - `facade.py` : `BackendFacade` — **seule API stable UI↔backend**. Échange via
    `BacktestRequest`/`BackendResponse` ; les erreurs remontent par
    `status`/`error_code`/`error_message`, **jamais de traceback brut côté UI**.
    Toute modification du contrat UI/backend passe ici.
  - `simulator.py` (référence) + `simulator_fast.py` / `performance_numba.py` /
    `sweep_numba.py` : chemins Numba JIT. Import en `try/except` avec fallback CPU
    pur si Numba absent (`HAS_NUMBA`). Le 1er sweep recompile le JIT (cache
    `.numba_cache`).
  - `result_store.py` / `store_v3.py` / `storage.py` : persistance des runs ;
    `load_project_env()` charge `.env` sans dépendre de python-dotenv (appelé au
    démarrage CLI et UI).
  - `walk_forward.py`, `optuna_optimizer.py`, `sweep.py` : optimisation et validation.
  - `audit_contract.py` / `audit_sentinels.py` : hashing/audit de config effective
    pour garantir le déterminisme et tracer les violations de contrat indicateur.

- **`strategies/`** — `StrategyBase` (abstrait) dans `base.py`. Contrat : `signals`
  standardisés (**1=long, -1=short, 0=flat**), retourne `StrategyResult`. Les
  stratégies s'enregistrent via le décorateur `@register_strategy("name")` dans un
  `_STRATEGY_REGISTRY` ; on les résout par `get_strategy(name)` / `list_strategies()`.
  `__init__.py` fait des imports **best-effort** (un fichier de stratégie manquant
  ne casse pas le package). `indicators_mapping.py` lie chaque stratégie aux
  indicateurs requis.

- **`indicators/`** — indicateurs techniques vectorisés NumPy, un module par
  indicateur, chacun avec son dataclass `<Nom>Settings`. `registry.py` :
  `register_indicator()` + `_INDICATOR_REGISTRY`, et `IndicatorRegistry` /
  `data/indicator_bank.py` pour le cache de calcul (`.indicator_cache`).

- **`agents/`** — génération de stratégies par LLM (mono-LLM Ollama actuellement).
  - `strategy_builder.py` / `simple_builder.py` / `builder_loop.py` : boucle
    itérative ; le code généré est **validé syntaxiquement (AST) puis chargé
    dynamiquement via importlib**, classe standardisée `BuilderGeneratedStrategy`,
    isolé dans `sandbox_strategies/<session_id>/`.
  - `llm_client.py`, `ollama_manager.py`, `ollama_runtime.py` : communication Ollama.
  - `builder_code_repair.py`, `builder_code_validation.py`,
    `pipeline_instrumentation.py`, `builder_diagnostics.py` : réparation sémantique,
    validation, instrumentation du pipeline de génération.
  - **NB** : infra multi-LLM legacy en cours de retrait (mode mono-LLM). Voir
    AGENTS.md pour l'état.

- **`ui/`** — Streamlit. `app.py` = bootstrap (PYTHONPATH, `load_project_env`,
  `st.set_page_config` avant tout rendu). Vues dans `main.py`, `sidebar.py`,
  `exec_tabs.py`, `results_hub.py`, `keeper_mode.py`, `builder_view.py`, etc.
  L'UI ne parle au backend **que** via `BackendFacade`.

- **`cli/`** — `python -m cli` → `cli.main()` parse les sous-commandes (dict
  `commands` dans `__init__.py`) et dispatch vers `cli/commands.py` (`cmd_*`).

- **`data/`** — `loader.py` charge CSV/Parquet/JSON/Feather. Le répertoire de
  données est résolu via les env vars **`BACKTEST_DATA_DIR`** / `TRADX_DATA_ROOT`.

## Conventions

- **Imports de chemins config sur Windows** : ne pas utiliser `Path("config/...")`
  relatif — `cwd` peut changer et provoquer `OSError [Errno 22]`. Résoudre depuis
  `Path(__file__).parent`.
- **Performance** : code numérique vectorisé NumPy ; les chemins chauds ont une
  version Numba avec fallback. `requirements-performance.txt` ajoute bottleneck,
  numexpr, cython.
- **Format** : black + isort (profil black) + ruff, line-length 120. `E402`
  ignoré (bootstrap GPU/PYTHONPATH intentionnellement avant imports).

## Documentation projet

- **`AGENTS.md`** — règles projet, référence CLI complète, presets rentables
  validés, et **journal d'interventions append-only** (la section d'introduction
  « Intouchables » ne doit jamais être modifiée). Fichier volumineux : grep ciblé.
- `AGEND_HISTORY.md` — journal historique complet (exclu de l'indexation).
- `GUIDE_CREATION_NOUVELLE_STRATEGIE.md` — guide pour ajouter une stratégie.
- `config/profitable_presets.toml` + `use_profitable_configs.py` — presets validés.

## Hygiène de contexte

Sont du **bruit** à exclure des recherches par défaut : `backtest_results/`,
`runs/`, `catalog/generated/`, `labs/`, `docs/` massifs, `*.html`/`Backtest Core_files/`,
les nombreux `.pytest_tmp*`, et les caches (`.numba_cache`, `.indicator_cache`,
`.mypy_cache`, `.ruff_cache`). `.copilotignore` / réglages VS Code portent déjà
cette politique.
