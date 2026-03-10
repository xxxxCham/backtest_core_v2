# Multi-LLM Builder

Cette variante existe uniquement dans `D:\backtest_core_multillm`.
Le projet source `D:\backtest_core` reste inchangé.

## Objectif

Ajouter un mode Builder autonome multi-LLM sans remplacer le Builder actuel.
Le moteur deterministe existant garde la main sur:

- le chargement des donnees
- les backtests
- le scoring
- la validation
- les resultats

Les LLM pilotent uniquement:

- la generation d'idees
- la generation/ajustement de la strategie
- la critique
- l'analyse risque
- la decision d'iteration

## Architecture

Le code dedie est dans:

- `core/llm_multi/model_discovery.py`
- `core/llm_multi/registry.py`
- `core/llm_multi/download_manager.py`
- `core/llm_multi/router.py`
- `core/llm_multi/roles.py`
- `core/llm_multi/session_manager.py`
- `core/llm_multi/prompt_templates.py`
- `core/llm_multi/adapters/strategy_builder_adapter.py`
- `core/llm_multi/config/default_profiles.json`

## Modes

- Mode par defaut: single-LLM
- Mode optionnel: multi-LLM

Le switch UI est visible uniquement dans le mode Builder autonome.
Le switch CLI est `python -m cli builder --multi-llm`.

## Profils

Profils fournis:

- `24GB_balanced`
- `fast_local`
- `finance_specialized`

Chaque profil mappe:

- `idea_llm`
- `builder_llm`
- `critic_llm`
- `risk_llm`
- `execution_router_llm`

## Decouverte locale

La detection locale scanne en priorite:

- `D:\models\huggingface`
- `D:\models\ollama`
- `C:\LLM-Local`
- `C:\Users\o3-Pro\Llama_ccp_win`

La logique verifie:

- manifests Ollama locaux
- repertoires HuggingFace exploitables
- `D:\models\models.json`

Elle distingue:

- modeles verifies localement
- references catalogue non verifiees

## Installation

L'installation automatique cible uniquement les modeles Ollama manquants.
La commande:

```powershell
python -m cli multi-llm --profile 24GB_balanced install
```

effectue des `ollama pull` seulement pour les roles encore non resolus.
Un dry-run est disponible:

```powershell
python -m cli multi-llm --profile 24GB_balanced --dry-run install
```

## Validation

```powershell
python -m cli multi-llm --json audit
python -m cli multi-llm --profile 24GB_balanced --json validate
python -m cli builder --objective "seed" --data BTCUSDT_1h.parquet --multi-llm --multi-llm-profile 24GB_balanced
```

## Notes de prudence

- Le mode multi-LLM est opt-in.
- Le Builder actuel reste le chemin par defaut.
- La decouverte locale evite les duplications massives et privilegie l'existant.
- Si Ollama n'est pas joignable, les manifests locaux restent utilises pour l'inventaire.
