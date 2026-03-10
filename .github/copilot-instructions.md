# Backtest Core — Instructions Copilot

Suivre `AGENTS.md` (source de verite) pour ce depot.

## Regles strictes

- Preferer modifier les fichiers existants plutot que creer.
- Ne pas creer de nouveaux fichiers Markdown de logs/notes/changelogs.
- Apres tout changement de code : ajouter exactement UNE entree a `AGENTS.md` -> Work Log.
- Travailler en micro-iterations : PLAN -> EDIT -> VERIFY -> LOG -> SELF-CRITIQUE.

## Architecture

Ce document decrit l'architecture globale (agents, moteur backtest, UI, CLI)
et les conventions a respecter pour maintenir un projet coherent.

## Modules

### agents/

| Fichier | Role | Notes |
|---------|------|-------|
| `analyst.py` | Agent Analyst | Analyse quantitative des performances |
| `strategist.py` | Agent Strategist | Generation de propositions de parametres |
| `critic.py` | Agent Critic | Evaluation overfitting et risques |
| `validator.py` | Agent Validator | Decision finale APPROVE/REJECT/ITERATE |
| `orchestrator.py` | Orchestrateur | Coordination du workflow complet |
| `backtest_executor.py` | Interface d'execution | `BacktestExecutor`, `BacktestRequest`, `BacktestResult`, `ExperimentHistory` (15/12/2025) |
| `autonomous_strategist.py` | Agent autonome | `AutonomousStrategist`, `OptimizationSession`, `create_autonomous_optimizer` (15/12/2025) |
| `integration.py` | Pont vers BacktestEngine | `run_backtest_for_agent()`, `create_optimizer_from_engine()`, `quick_optimize()` (15/12/2025) |
| `model_config.py` | Configuration multi-modeles | `RoleModelConfig`, `ModelCategory`, `KNOWN_MODELS`, selection par role (13/12/2025) |

#### Agents Phase 3 - 14/12/2025

Couvre les agents LLM, la machine a etats, et l'orchestration multi-etapes.

#### Mode Autonome - Workflow iteratif avec backtests reels

```text
BASELINE -> [ANALYZE -> PROPOSE -> BACKTEST -> EVALUATE]* -> ACCEPT/STOP
```

#### Mode Orchestre - State Machine

```text
INIT -> ANALYZE -> PROPOSE -> CRITIQUE -> VALIDATE -> [APPROVED|REJECTED|ITERATE]
                                                          |
                                                      ANALYZE (boucle)
```

#### GPU Memory Optimization (13/12/2025)

- Le LLM est **decharge du GPU** avant chaque backtest
- Libere la VRAM pour les calculs NumPy/CuPy
- **Recharge automatiquement** apres le backtest
- Active par defaut : `unload_llm_during_backtest=True`
- Context manager : `gpu_compute_context("model_name")`

#### Exemple Mode Autonome (avec integration vraie)

```python
from agents import create_optimizer_from_engine, quick_optimize
from agents.llm_client import LLMConfig, LLMProvider

# Méthode 1: Contrôle complet avec BacktestEngine réel
config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.2")
strategist, executor = create_optimizer_from_engine(
    llm_config=config,
    strategy_name="ema_cross",  # Stratégie du registre
    data=ohlcv_df,              # DataFrame OHLCV
    use_walk_forward=True,      # Activer validation anti-overfitting
)

session = strategist.optimize(
    executor=executor,
    initial_params={"fast_period": 10, "slow_period": 21},
    param_bounds={"fast_period": (5, 20), "slow_period": (15, 50)},
    max_iterations=10,
)
print(f"Best Sharpe: {session.best_result.sharpe_ratio}")

# Méthode 2: Raccourci rapide
session = quick_optimize(config, "ema_cross", df, max_iterations=10)

# Méthode 3: Context manager pour calculs manuels
from agents import gpu_compute_context
with gpu_compute_context("deepseek-r1:32b"):
    # GPU libre pour calculs numpy/cupy
    result = heavy_computation()
# LLM rechargé automatiquement
```

#### Configuration LLM (variables d'environnement)

- `BACKTEST_LLM_PROVIDER` : `ollama` ou `openai`
- `BACKTEST_LLM_MODEL` : ex: `llama3.2`, `gpt-4`
- `OLLAMA_HOST` : URL Ollama (defaut: `http://localhost:11434`)
- `OPENAI_API_KEY` : Cle API OpenAI

### backtest/

| Fichier | Role |
|---------|------|
| `engine.py` | Orchestration du pipeline de backtest |
| `simulator.py` | Simulation trades CPU |
| `simulator_fast.py` | Simulation Numba |
| `performance.py` | Metriques de performance (Sharpe, drawdown, etc.) |
| `validation.py` | Walk-forward validation |
| `execution.py` | Execution modelisee (spread/slippage) |
| `facade.py` | Facade UI <-> moteur |

### strategies/

Pattern obligatoire : Decorateur `@register_strategy` + heritage `StrategyBase`

```python
@register_strategy("nom_strategie")
class MaStrategy(StrategyBase):
    @property
    def required_indicators(self) -> List[str]:
        return ["bollinger", "atr"]

    def generate_signals(self, df, indicators, params) -> pd.Series:
        # Retourne: 1=long, -1=short, 0=flat
```

| Stratégie | Fichier | Indicateurs |
|-----------|---------|-------------|
| `bollinger_atr` | `bollinger_atr.py` | bollinger, atr |
| `bollinger_dual` | `bollinger_dual.py` | bollinger, sma/ema (13/12/2025) |
| `ema_cross` | `ema_cross.py` | ema |
| `macd_cross` | `macd_cross.py` | macd |
| `rsi_reversal` | `rsi_reversal.py` | rsi |
| `atr_channel` | `atr_channel.py` | atr |
| `ma_crossover` | `ma_crossover.py` | sma/ema |
| `ema_stochastic_scalp` | `ema_stochastic_scalp.py` | ema, stochastic |

### indicators/

Registre centralisé dans `registry.py`. Enregistrement via `register_indicator()`.

| Indicateur | Fichier | Colonnes requises | Retour |
|------------|---------|-------------------|--------|
| `bollinger` | `bollinger.py` | close | `(upper, middle, lower)` |
| `atr` | `atr.py` | high, low, close | `np.array` |
| `rsi` | `rsi.py` | close | `np.array` |
| `ema` / `sma` | `ema.py` | close | `np.array` |
| `macd` | `macd.py` | close | `dict{macd, signal, histogram}` |
| `adx` | `adx.py` | high, low, close | `dict{adx, plus_di, minus_di}` |
| `stochastic` | `stochastic.py` | high, low, close | `(stoch_k, stoch_d)` |
| `vwap` | `vwap.py` | high, low, close, volume | `np.array` (13/12/2025) |
| `donchian` | `donchian.py` | high, low | `dict{upper, middle, lower}` (13/12/2025) |
| `cci` | `cci.py` | high, low, close | `np.array` (13/12/2025) |
| `keltner` | `keltner.py` | high, low, close | `dict{middle, upper, lower}` (13/12/2025) |
| `mfi` | `mfi.py` | high, low, close, volume | `np.array` (13/12/2025) |
| `williams_r` | `williams_r.py` | high, low, close | `np.array` (13/12/2025) |
| `momentum` | `momentum.py` | close | `np.array` (13/12/2025) |
| `obv` | `obv.py` | close, volume | `np.array` (13/12/2025) |
| `roc` | `roc.py` | close | `np.array` (13/12/2025) |
| `aroon` | `aroon.py` | high, low | `dict{aroon_up, aroon_down}` (13/12/2025) |
| `supertrend` | `supertrend.py` | high, low, close | `dict{supertrend, direction}` (13/12/2025) |
| `ichimoku` | `ichimoku.py` | high, low, close | `dict{tenkan, kijun, senkou_a, senkou_b, chikou, cloud_position}` (14/12/2025) |
| `psar` | `psar.py` | high, low, close | `dict{sar, trend, signal}` (14/12/2025) |
| `stoch_rsi` | `stoch_rsi.py` | close | `dict{k, d, signal}` (14/12/2025) |
| `vortex` | `vortex.py` | high, low, close | `dict{vi_plus, vi_minus, signal, oscillator}` (14/12/2025) |

### data/

| Fichier | Rôle |
|---------|------|
| `loader.py` | `load_ohlcv()`, `discover_available_data()` |
| `indicator_bank.py` | IndicatorBank - Cache disque intelligent avec TTL (14/12/2025) |
| `sample_data/` | Données de test, format `SYMBOL_TIMEFRAME.ext` |

### ui/

**Fichier unique** : `app.py` - Interface Streamlit

⚠️ **Règle stricte** : AUCUNE logique de trading dans ce dossier.

| Fonctionnalité | État | Notes |
|----------------|------|-------|
| Sélection stratégie | ✅ | Dropdown depuis registre |
| Configuration paramètres | ✅ | Sliders avec contraintes |
| Granularité globale | ✅ | **Checkbox désactivée par défaut** (12/12/2025) |
| Granularité par paramètre | 🔜 TODO | À implémenter |
| Visualisation résultats | ✅ | Plotly charts |
| Mode sweep/optimisation | ✅ | Grille paramétrique |

### utils/

| Fichier | Rôle |
|---------|------|
| `config.py` | `Config` dataclass, singleton, fees/slippage en BPS |
| `parameters.py` | `ParameterSpec`, `Preset`, système de granularité, **Contraintes** (12/12/2025) |
| `log.py` | Logging centralisé (legacy) |
| `observability.py` | **Observabilité intelligente** : `get_obs_logger`, `trace_span`, `PerfCounters`, `DiagnosticPack` (12/12/2025) |
| `health.py` | `HealthMonitor`, surveillance CPU/RAM/GPU/Disk (12/12/2025) |
| `memory.py` | `MemoryManager`, `ManagedCache`, nettoyage automatique (12/12/2025) |
| `circuit_breaker.py` | `CircuitBreaker`, protection échecs répétés (12/12/2025) |
| `checkpoint.py` | `CheckpointManager`, sauvegarde/reprise état (12/12/2025) |
| `error_recovery.py` | `RetryHandler`, `ErrorClassifier`, récupération erreurs (12/12/2025) |
| `gpu_oom.py` | `GPUOOMHandler`, gestion OOM GPU, fallback CPU (12/12/2025) |

#### Observabilité (12/12/2025)

Système de debug intelligent avec zéro overhead en prod :

```python
from utils.observability import get_obs_logger, trace_span, generate_run_id

# Logger avec contexte corrélé
run_id = generate_run_id()  # "a1b2c3d4"
logger = get_obs_logger(__name__, run_id=run_id, strategy="ema_cross")

# Span chronométré (zéro coût si DEBUG désactivé)
with trace_span(logger, "indicators", count=5):
    # ... calculs ...
    pass

# Activation: BACKTEST_LOG_LEVEL=DEBUG ou toggle UI
```

### performance/

| Fichier | Rôle |
|---------|------|
| `gpu.py` | Calculs GPU accélérés avec CuPy |
| `memory.py` | Profilage mémoire |
| `monitor.py` | Monitoring performances |
| `parallel.py` | Parallélisation des calculs |
| `profiler.py` | Profilage temps d'exécution |
| `device_backend.py` | `ArrayBackend`, basculement NumPy/CuPy transparent (12/12/2025) |

#### Système de Contraintes (12/12/2025)

Le système de contraintes permet de filtrer les combinaisons de paramètres invalides :

```python
from utils.parameters import ConstraintValidator

validator = ConstraintValidator()
validator.add_greater_than('slow_period', 'fast_period')
validator.add_ratio_min('slow_period', 'fast_period', ratio=1.5)

# Filtrer une grille
valid_grid = validator.filter_grid(param_grid)
```

Types de contraintes: `greater_than`, `less_than`, `ratio_min`, `ratio_max`, `difference_min`, `min_value`, `max_value`.

### tests/

| Fichier/Dossier | Role |
|-----------------|------|
| `tests/` | Suite pytest principale (unit + integration) |
| `test_*.py` | Tests additionnels (smoke/regression) |

### config/

| Fichier | Rôle |
|---------|------|
| `indicator_ranges.toml` | Plages d'optimisation pour tous indicateurs/stratégies (13/12/2025) |

---

## Mode CLI

Le mode CLI permet le contrôle programmatique du moteur de backtest.

| Commande | Status | Description |
|----------|--------|-------------|
| `backtest` | ✅ | Exécuter un backtest simple (12/12/2025) |
| `sweep` | ✅ | Optimisation paramétrique (13/12/2025) |
| `optuna` | ✅ | Optimisation bayésienne (16/12/2025) |
| `list` | ✅ | Lister stratégies/indicateurs/données (12/12/2025) |
| `info` | ✅ | Infos détaillées sur une ressource (12/12/2025) |
| `validate` | ✅ | Valider configuration (12/12/2025) |
| `export` | ✅ | Exporter résultats (HTML/CSV/Excel) (13/12/2025) |
| `visualize` | ✅ | Visualisation interactive candlesticks+trades (17/12/2025) |

#### Point d'entree

`python __main__.py [COMMANDE] [OPTIONS]`

#### Variables d'environnement

- `BACKTEST_DATA_DIR` : Chemin vers fichiers Parquet/CSV
- `UNLOAD_LLM_DURING_BACKTEST` : `False` (défaut, CPU-only) ou `True` (GPU optimization)

#### Exemples

```powershell
$env:BACKTEST_DATA_DIR = "D:\chemin\vers\parquet"
python __main__.py list data
python __main__.py backtest -s ema_cross -d BTCUSDC_1h.parquet
python __main__.py optuna -s ema_cross -d BTCUSDC_1h.parquet -n 100
python __main__.py validate --all
```

---

## Conventions

- **Calculs vectorisés NumPy** - Pas de boucles Python sur séries de prix
- **Signaux** : `1` (long), `-1` (short), `0` (neutre)
- **Frais en BPS** : `fees_bps=10` = 0.1%
- **Seed reproductibilité** : `np.random.seed(42)`
- **Docstrings en français** avec blocs `Args/Returns/Raises`
- **Tests pytest obligatoires** pour toute nouvelle fonctionnalité

---

## Commandes

```powershell
# Environnement
& .venv/Scripts/Activate.ps1

# Tests
python run_tests.py           # Standard
python run_tests.py -v        # Verbose
python run_tests.py --coverage

# Interface
streamlit run ui/app.py

# Demo
python demo/quick_test.py
```

---

## Directive de maintenance

> **IMPORTANT pour l'agent IA** : Après chaque modification de code, mettre à jour ce fichier.

### Règles de mise à jour

1. **Nouveau fichier/module** → Ajouter dans la table du module concerné
2. **Nouvelle fonctionnalité** → Mettre à jour la colonne "État" avec ✅ ou 🔜
3. **Modification comportement** → Annoter avec la date `(JJ/MM/AAAA)`
4. **Bug fix majeur** → Mentionner dans les notes
5. **Ne pas créer de section chronologique** → Intégrer au bon endroit

### Exemple de mise à jour

```markdown
| Granularité par paramètre | 🔜 TODO | À implémenter |
```

devient apres implementation :

```markdown
| Granularité par paramètre | ✅ | Sliders individuels (15/12/2025) |
```

---

## Index des Modifications

> Liste chronologique des changements avec liens vers les sections.

| Date | Modification | Section |
|------|--------------|---------|
| 12/12/2025 | Création CLI_REFERENCE.md pour mode CLI | [Mode CLI](#mode-cli) |
| 12/12/2025 | Ajout directive LLM en tete de fichier | [Directive](#directive-de-maintenance) |
| 12/12/2025 | Ajout 11 indicateurs: vwap, donchian, cci, keltner, mfi, williams_r, momentum, obv, roc, aroon, supertrend | indicators/ |
| 12/12/2025 | Ajout stratégie bollinger_dual | strategies/ |
| 12/12/2025 | Création config/indicator_ranges.toml | config/ |
| 12/12/2025 | Granularité globale : checkbox désactivée par défaut | ui/ |
| 12/12/2025 | Création du fichier copilot-instructions.md | [Architecture](#architecture) |
| 12/12/2025 | **Implémentation CLI** : `__main__.py`, `cli/__init__.py`, `cli/commands.py` | [Mode CLI](#mode-cli) |
| 12/12/2025 | CLI: commandes list, info, validate, backtest fonctionnelles | [Mode CLI](#mode-cli) |
| 12/12/2025 | Support $BACKTEST_DATA_DIR pour fichiers parquet | data/ |
| 12/12/2025 | Auto-génération param_ranges depuis parameter_specs | strategies/ |
| 13/12/2025 | **Implémentation sweep** : Commande sweep fonctionnelle avec grille paramétrique | [Mode CLI](#mode-cli) |
| 13/12/2025 | **Implémentation export** : Commande export HTML/CSV/Excel | [Mode CLI](#mode-cli) |
| 13/12/2025 | Correction bug metrics.to_dict() dans sweep | backtest/ |
| 13/12/2025 | Arguments globaux (-v, -q, --no-color) hérités par sous-commandes | [Mode CLI](#mode-cli) |
| 12/12/2025 | **Phase 1 - Métriques Tier S** : SQN, Recovery Factor, Ulcer Index, Martin Ratio | backtest/ |
| 12/12/2025 | **Phase 1 - Walk-Forward Validation** : validation.py, anti-overfitting | backtest/ |
| 12/12/2025 | **Phase 1 - Constraints System** : ConstraintValidator dans parameters.py | utils/ |
| 13/12/2025 | **Consolidation tests** : Fusion test_indicators.py + test_indicators_new.py | tests/ |
| 13/12/2025 | **Nettoyage** : Suppression validate_backtest.py (redondant avec demo/) | [Architecture](#architecture) |
| 14/12/2025 | **Phase 2 - Ichimoku Cloud** : Indicateur complet (tenkan, kijun, senkou_a/b, chikou) | indicators/ |
| 14/12/2025 | **Phase 2 - Parabolic SAR** : Indicateur avec trend et signals | indicators/ |
| 14/12/2025 | **Phase 2 - Stochastic RSI** : RSI + oscillateur stochastique | indicators/ |
| 14/12/2025 | **Phase 2 - Vortex** : VI+, VI-, oscillator et signals | indicators/ |
| 14/12/2025 | **Phase 2 - IndicatorBank** : Cache disque intelligent avec TTL | data/ |
| 14/12/2025 | **Tests Phase 2** : 34 tests pour nouveaux indicateurs et cache | tests/ |
| 14/12/2025 | **GPUDeviceManager** : Gestion prudente mono-GPU avec verrouillage | performance/ |
| 14/12/2025 | **Phase 3 - State Machine** : AgentState, StateMachine, transitions validées | [agents/](#agents-phase-3---14122025) |
| 14/12/2025 | **Phase 3 - LLM Client** : Support Ollama et OpenAI unifié | [agents/](#agents-phase-3---14122025) |
| 14/12/2025 | **Phase 3 - Agent Analyst** : Analyse quantitative performances | [agents/](#agents-phase-3---14122025) |
| 14/12/2025 | **Phase 3 - Agent Strategist** : Génération propositions paramètres | [agents/](#agents-phase-3---14122025) |
| 14/12/2025 | **Phase 3 - Agent Critic** : Évaluation overfitting et risques | [agents/](#agents-phase-3---14122025) |
| 14/12/2025 | **Phase 3 - Agent Validator** : Décisions APPROVE/REJECT/ITERATE | [agents/](#agents-phase-3---14122025) |
| 14/12/2025 | **Phase 3 - Orchestrator** : Coordination workflow complet | [agents/](#agents-phase-3---14122025) |
| 14/12/2025 | **Tests Phase 3** : 36 tests pour agents LLM et orchestrator | tests/ |
| 15/12/2025 | **Phase 3 - BacktestExecutor** : Interface d'exécution backtests pour agents | [agents/](#agents-phase-3---14122025) |
| 15/12/2025 | **Phase 3 - AutonomousStrategist** : Agent autonome avec boucle d'itération | [agents/](#agents-phase-3---14122025) |
| 15/12/2025 | **Phase 3 - ExperimentHistory** : Tracking des expériences et analyse sensibilité | [agents/](#agents-phase-3---14122025) |
| 15/12/2025 | **Phase 3 - Integration** : Pont `integration.py` vers BacktestEngine réel | [agents/](#agents-phase-3---14122025) |
| 15/12/2025 | **Tests Autonome** : 28 tests système autonome + 13 tests intégration (285 tests totaux) | tests/ |
| 13/12/2025 | **GPU Memory Manager** : Déchargement/rechargement LLM pendant les backtests | [agents/](#agents-phase-3---14122025) |
| 13/12/2025 | **Audit Code - Corrections Critiques** : Var env GPU unload, protection div/0, try/except parse_json, validation timestamps/bounds | Multiple |
| 12/12/2025 | **Phase 2 - Monte Carlo Sampling** : Échantillonnage LHS/Sobol pour optimisation | backtest/ |
| 12/12/2025 | **Phase 4 - Circuit Breaker** : Protection échecs répétés, états CLOSED/OPEN/HALF_OPEN | utils/ |
| 12/12/2025 | **Phase 4 - Checkpoint Manager** : Sauvegarde/reprise automatique état opérations | utils/ |
| 12/12/2025 | **Phase 1 - Realistic Execution** : Spread/slippage dynamique, latence, impact marché | backtest/ |
| 12/12/2025 | **Phase 4 - Health Monitor** : Surveillance CPU/RAM/GPU/Disk, alertes configurables | utils/ |
| 12/12/2025 | **Phase 4 - Memory Manager** : Gestion mémoire, ManagedCache LRU, auto-cleanup | utils/ |
| 12/12/2025 | **Tests Phase 4** : 52 nouveaux tests (430 tests totaux) | tests/ |
| 12/12/2025 | **Phase 2.5 - Pareto Pruning** : Optimisation multi-objectif, frontière Pareto | backtest/ |
| 12/12/2025 | **Phase 2.6 - Device Backend** : ArrayBackend NumPy/CuPy transparent | performance/ |
| 12/12/2025 | **Phase 4.5 - Error Recovery** : RetryHandler, ErrorClassifier, backoff exponentiel | utils/ |
| 12/12/2025 | **Phase 4.6 - GPU OOM Handler** : Gestion OOM, fallback CPU automatique | utils/ |
| 12/12/2025 | **Tests Finaux** : 70 nouveaux tests Phase 2/4 (500 tests totaux) | tests/ |
| 12/12/2025 | **Façade UI↔Backend** : `BackendFacade`, contrats d'interface, `UIPayload` | backtest/ |
| 12/12/2025 | **Hiérarchie d'erreurs** : `BacktestError`, `UserInputError`, `DataError` | backtest/ |
| 12/12/2025 | **Tests Façade** : 21 tests d'intégration (603 tests totaux) | tests/ |
| 12/12/2025 | **Observabilité** : `observability.py`, `get_obs_logger`, `trace_span`, `PerfCounters` | utils/ |
| 12/12/2025 | **Tests Observabilité** : 17 tests (620 tests totaux) | tests/ |
| 16/12/2025 | **Optuna Integration** : `optuna_optimizer.py`, optimisation bayésienne TPE/CMA-ES | backtest/ |
| 16/12/2025 | **CLI optuna** : Commande CLI pour optimisation bayésienne avec pruning et multi-objectif | [Mode CLI](#mode-cli) |
| 16/12/2025 | **Tests Optuna** : 32 tests (652 tests totaux) | tests/ |
| 17/12/2025 | **Visualization Module** : `utils/visualization.py`, graphiques candlestick+trades Plotly | utils/ |
| 17/12/2025 | **CLI visualize** : Commande CLI pour visualisation interactive avec rapport HTML | [Mode CLI](#mode-cli) |
| 17/12/2025 | **Tests Visualization** : 24 tests (676 tests totaux) | tests/ |
| 13/12/2025 | **Unification Search Space Stats** : `compute_search_space_stats()` dans `utils/parameters.py` | utils/ |
| 13/12/2025 | **UI Grille Stats Unifiées** : Utilisation `compute_search_space_stats()` dans l'UI Grille | ui/ |
| 13/12/2025 | **CLI Sweep Stats** : Affichage détaillé par paramètre dans `cmd_sweep()` | [Mode CLI](#mode-cli) |
| 13/12/2025 | **get_strategy_param_space()** : Extension de `get_strategy_param_bounds()` avec step | [agents/](#agents-phase-3---14122025) |
| 13/12/2025 | **UI LLM Estimation** : Affichage estimation d'espace discret dans mode LLM | ui/ |
| 13/12/2025 | **create_orchestrator_with_backtest()** : Branchement Orchestrator sur `run_backtest_for_agent()` | [agents/](#agents-phase-3---14122025) |
| 13/12/2025 | **Multi-Model Config** : `model_config.py`, attribution modèles par rôle, sélection aléatoire | [agents/](#agents-phase-3---14122025) |
| 13/12/2025 | **UI Multi-Modèles** : Interface configuration modèles par rôle (Analyst/Strategist/Critic/Validator) | ui/ |
| 13/12/2025 | **ENVIRONMENT.md** : Documentation complète variables d'env, configuration GPU/LLM/logging | [Mode CLI](#mode-cli) |
| 13/12/2025 | **.env.example** : Template enrichi avec GPU unload, LLM config, walk-forward | [Architecture](#architecture) |
| 13/12/2025 | **README.md** : Section Documentation avec liens vers ENVIRONMENT.md, configuration critique GPU | [Architecture](#architecture) |
| 13/12/2025 | **Refactorisation Pydantic** : Validation AnalystAgent avec Pydantic v2 (3 modèles, 29 tests 100% pass) | [agents/](#agents-phase-3---14122025) |
| 13/12/2025 | **Système Templates Jinja2** : Centralisation prompts LLM (4 templates, utils/template.py, 30 tests) | [agents/](#agents-phase-3---14122025) |
| 13/12/2025 | **Stats Espace de Recherche Unifiées** : `compute_search_space_stats()` intégré dans CLI, UI, sweep, agents (29 tests) | utils/ |
| 17/12/2025 | **Optuna Early Stopping** : Callback d'arrêt anticipé après N trials sans amélioration (21 tests) | backtest/ |
| 13/12/2025 | **Performance Optimizations v1.8.0** : Vectorisation complète + Numba JIT + GPU (8 fichiers, 2455 lignes) | performance/ |
| 17/12/2025 | **agent.md** : Création fichier instructions agent LLM optimisé pour le projet | [Architecture](#architecture) |
| 18/12/2025 | **Système Logs Orchestration LLM** : `orchestration_logger.py`, 20+ types d'actions, intégration AutonomousStrategist | [agents/](#agents-phase-3---14122025) |
| 18/12/2025 | **UI Orchestration Viewer** : `ui/orchestration_viewer.py`, timeline/résumé/métriques en temps réel | ui/ |
| 18/12/2025 | **Intégration UI LLM** : Affichage logs orchestration dans mode "Optimisation LLM" de app.py | ui/ |
| 18/12/2025 | **Tests Orchestration** : `test_ui_orchestration_integration.py`, 5 tests (100% pass) | tests/ |
| 18/12/2025 | **Documentation Orchestration** : `docs/ORCHESTRATION_LOGS.md`, guide complet utilisation et API | [Architecture](#architecture) |
| 25/12/2025 | Multi-agent parity: n_workers (parallel proposals), UI live orchestration, JSONL persistence, Ollama retries | [agents/](#agents-phase-3---14122025) |
| 25/12/2025 | Bugfix templates: `critic.jinja2` robuste aux variables WF manquantes + test non-régression | [agents/](#agents-phase-3---14122025) |
| 30/12/2025 | **Bugfix AutonomousStrategist** : Correction AttributeError `self.llm_config` → accès via `self.llm.config` | [agents/](#agents-phase-3---14122025) |

---

Derniere mise a jour : 30/12/2025 (v1.8.3)

