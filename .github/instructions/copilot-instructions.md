---
applyTo: "**"
---

# Instructions Workspace — backtest_core_v2

## Langue et style
- Répondre toujours en **français**, concis et factuel.
- Patches ciblés sur les fichiers existants ; pas de création de fichiers superflus.

## Projet
Moteur de backtest algorithmique en Python avec :
- **Builder LLM autonome** : génère et évalue des stratégies de trading via Ollama (local) ou OpenAI.
- **UI Streamlit** (`ui/`) : interface de pilotage du backtest, du sweep, d'Optuna et du Builder.
- **Moteur** (`backtest/engine.py`, `backtest/simulator_fast.py`) : exécution Numba/GPU.
- **Stratégies versionnées** (`strategies/`) et **indicateurs** (`indicators/`).
- **Store canonique** : `BacktestStoreV3` (`backtest/store_v3.py`).
- **LLM multi-rôles** : `core/llm_multi/`, orchestration dans `agents/`.

## Conventions critiques
- `AGENTS.md` est le **point d'entrée obligatoire** ; son journal est **append-only** (ne jamais supprimer d'entrées).
- `AGEND_HISTORY.md` contient l'historique détaillé — **exclu de l'indexation Copilot**.
- Tests : `pytest tests/` ; toujours vérifier avec `python -m py_compile` avant de proposer un patch.
- Données canoniques : `D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet`
- Environnement Python : `.venv/` à la racine, activer avec `.venv\Scripts\Activate.ps1`.

## Modèles LLM locaux actifs
- `gemma4:26b`, `gemma4:31b` (Ollama, GPU RTX 5080 / RTX 3060 Ti)
- Registre central : `agents/model_config.py` (`KNOWN_MODELS`)

## À éviter
- Ne pas modifier les entrées du journal dans `AGENTS.md`.
- Ne pas hardcoder de chemins de données anciens (`gestionnaire_telechargement_multi-timeframe` sans `_clean`).
- Ne pas ajouter de refactoring non demandé ni de docstrings sur du code non modifié.
