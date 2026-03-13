# Rapport Détaillé : Intégration Ollama dans Backtest Core V2

## Vue d'ensemble

Le projet `backtest_core_v2` intègre Ollama comme fournisseur LLM principal pour l'optimisation multi-agents des stratégies de trading. L'architecture repose sur une abstraction unifiée `LLMClient` qui masque les différences entre Ollama et OpenAI, avec une gestion spécialisée de la mémoire GPU et une découverte automatique des modèles.

**Date de génération** : 13 mars 2026
**Version du projet** : backtest_core_v2 (main branch)
**Environnement cible** : Windows 11, Python 3.12+, GPU RTX 5080/RTX 2060

## Architecture Générale

### 1. Couches d'Abstraction

```
┌─────────────────┐
│   CLI/UI        │ ← Interface utilisateur (Streamlit, CLI)
│   (ui/, cli/)   │
├─────────────────┤
│ Orchestrateur   │ ← Coordination multi-agents
│ (agents/)       │   (Analyst/Strategist/Critic/Validator)
├─────────────────┤
│ LLMClient       │ ← Abstraction unifiée
│ (agents/)       │   (OllamaClient/OpenAIClient)
├─────────────────┤
│ Gestion GPU     │ ← GPUMemoryManager, context managers
│ (agents/)       │
├─────────────────┤
│ Découverte      │ ← ModelDiscovery, model_loader
│ (core/, utils/) │
├─────────────────┤
│ Daemon Ollama   │ ← Service REST API
│ (localhost)     │   (/api/chat, /api/generate, /api/tags)
└─────────────────┘
```

### 2. Points d'Entrée Principaux

#### CLI (`cli/commands.py`)
- **Commande** : `python -m cli llm-optimize`
- **Fonction principale** : `_cmd_llm_optimize_single()`
- **Flux d'exécution** :
  1. Chargement données OHLCV via `data.loader.load_ohlcv()`
  2. Création `LLMConfig` avec `provider=LLMProvider.OLLAMA`
  3. Appel `create_orchestrator_with_backtest()`
  4. Lancement `orchestrator.run()`
  5. Export résultats vers JSON si `--output` spécifié

#### UI Streamlit (`ui/main.py`)
- **Mode** : "Mode LLM Optimization"
- **Composants impliqués** :
  - `ui/components/model_selector.py` : Sélection modèle avec formatage VRAM
  - `ui/sidebar.py` : Configuration multi-agent/multi-model
  - `ui/builder_view.py` : Exécution et affichage résultats
- **Flux d'exécution** :
  1. Sélection modèle dans dropdown avec métadonnées GPU
  2. Configuration rôles (Analyst/Strategist/Critic/Validator)
  3. Exécution via `create_orchestrator_with_backtest()`
  4. Affichage résultats temps réel avec métriques

## Architecture Détaillée des Connexions

### 1. Client LLM (`agents/llm_client.py`)

#### Classe `LLMConfig`
```python
@dataclass
class LLMConfig:
    provider: LLMProvider = LLMProvider.OLLAMA  # OLLAMA ou OPENAI
    model: str = "llama3.2"                     # ex: "deepseek-r1:32b"
    ollama_host: str = "http://127.0.0.1:11434" # Host Ollama
    temperature: float = 0.7
    max_tokens: int = 1000
    timeout_seconds: float = 60.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
```

**Méthodes de configuration** :
- `from_env()` : Chargement depuis variables d'environnement
- Validation automatique des paramètres
- Support configuration multi-modèles par rôle

#### Classe `OllamaClient(LLMClient)`

**Initialisation** :
- Timeout adaptatif selon type de modèle (15min pour reasoning models)
- Client HTTP httpx avec timeout configuré
- Gestion des retries avec backoff exponentiel
- Métriques d'utilisation (total_tokens, total_requests)

**Méthodes principales** :

##### `is_available()` → bool
- **Endpoint** : `GET /api/tags`
- **Timeout** : 5 secondes
- **Retour** : True si status 200
- **Logging** : Warning si indisponible

##### `list_models()` → List[str]
- **Endpoint** : `GET /api/tags`
- **Parsing** : Extraction `models[].name`
- **Gestion erreurs** : Retour liste vide si échec

##### `chat()` → LLMResponse
- **Endpoint primaire** : `POST /api/chat`
- **Format** : Messages structurés OpenAI-compatible
- **Fallback** : `/api/generate` si 404
- **Retry logic** : Backoff exponentiel sur timeout/erreurs
- **Timeout adaptatif** : 15min pour modèles reasoning

##### `chat_stream()` → LLMResponse
- **Endpoint** : `POST /api/chat` avec `stream: true`
- **Callback** : `on_chunk(text)` pour chaque token
- **Fallback** : `chat()` classique si streaming échoue
- **Gestion erreurs** : Callback sécurisé (pas d'exception utilisateur)

#### Flux de Communication Détaillé

```
OllamaClient.chat(messages, **kwargs)
    ↓
1. Validation paramètres + timeout adaptatif
    ↓
2. Construction payload JSON:
   {
     "model": "deepseek-r1:32b",
     "messages": [
       {"role": "system", "content": "You are a trading analyst..."},
       {"role": "user", "content": "Analyze this strategy..."}
     ],
     "stream": false,
     "options": {
       "temperature": 0.7,
       "num_predict": 1000,
       "top_p": 0.9
     }
   }
    ↓
3. POST /api/chat avec timeout adaptatif
    ↓
4. Gestion erreurs:
   - 404 → Fallback /api/generate
   - TimeoutException → Retry avec backoff
   - Autres → Retry immédiat
    ↓
5. Parsing réponse JSON:
   {
     "message": {"content": "Analysis complete..."},
     "done": true,
     "prompt_eval_count": 150,
     "eval_count": 200,
     "total_duration": 45000000000
   }
    ↓
6. Construction LLMResponse:
   - content: message.content
   - model: config.model
   - provider: LLMProvider.OLLAMA
   - tokens: prompt_eval_count + eval_count
   - latency_ms: calculé
   - raw_response: dict complet
    ↓
7. Parsing JSON si mode activé
    ↓
8. Retour réponse + mise à jour métriques
```

### 2. Gestion Mémoire GPU (`agents/ollama_manager.py`)

#### Classe `GPUMemoryManager`

**Attributs** :
- `model_name`: Nom du modèle Ollama
- `ollama_host`: URL du serveur
- `warmup_prompt`: Prompt de réchauffement
- `verbose`: Affichage logs
- `_current_state`: État mémoire actuel

**Méthodes principales** :

##### `is_model_loaded()` → bool
- **Endpoint** : `GET /api/ps`
- **Vérification** : Présence modèle dans `models[].name`
- **Retour** : True si chargé en mémoire

##### `unload(context_messages)` → LLMMemoryState
- **Action** : `POST /api/generate` avec `keep_alive: 0`
- **Métriques** : Temps d'unload en ms
- **État** : Sauvegarde contexte conversation
- **Logging** : Confirmation déchargement

##### `reload(state, restore_context)` → bool
- **Action** : `POST /api/generate` avec prompt warmup
- **Contexte** : Restauration messages précédents si demandé
- **Timeout** : 120 secondes pour gros modèles
- **Métriques** : Temps de reload en ms

#### Context Manager `gpu_compute_context()`

```python
@contextmanager
def gpu_compute_context(model_name: str, **kwargs) -> Generator[GPUMemoryManager, None, None]:
    manager = GPUMemoryManager(model_name, **kwargs)

    # Déchargement automatique
    state = manager.unload()

    try:
        yield manager  # GPU libre pour calculs
    finally:
        # Rechargement automatique
        manager.reload(state)
```

**Utilisation typique** :
```python
# Dans agents/autonomous_strategist.py
with gpu_compute_context("deepseek-r1:32b"):
    # LLM déchargé → VRAM disponible
    result = engine.run(df, strategy="ema_cross", params=best_params)
# LLM rechargé automatiquement
```

#### Démarrage Daemon (`ensure_ollama_running()`)

**Étapes** :
1. **Vérification** : `GET /api/tags` (timeout 2s)
2. **Si indisponible** :
   - Vérification host local vs distant
   - Construction environnement (OLLAMA_HOST, OLLAMA_MODELS, CUDA_VISIBLE_DEVICES)
   - Lancement `ollama serve` en arrière-plan
3. **Attente** : Boucle 10s avec vérifications régulières
4. **Confirmation** : Liste modèles pour valider fonctionnement

**Variables d'environnement gérées** :
- `OLLAMA_HOST`: URL du serveur
- `OLLAMA_MODELS`: Chemin store modèles
- `CUDA_VISIBLE_DEVICES`: Pinning GPU (si applicable)

### 3. Découverte de Modèles (`core/llm_multi/model_discovery.py`)

#### Classe `ModelInventory`

**Attributs** :
- `discovered_models`: Liste `DiscoveredModel`
- `scanned_roots`: Chemins scannés
- `missing_roots`: Chemins absents
- `warnings`: Messages d'avertissement
- `live_ollama_host`: Host Ollama vérifié
- `live_ollama_reachable`: Statut connexion

#### Classe `DiscoveredModel`

**Attributs** :
- `name`: Nom canonique
- `backend`: "ollama" | "huggingface" | "gguf"
- `source`: Origine découverte
- `verified_available`: Présence vérifiée
- `path`: Chemin fichier/dossier
- `exists_on_disk`: Existence physique
- `live`: Chargé dans Ollama
- `aliases`: Liste noms alternatifs
- `role_hints`: Rôles suggérés (builder_llm, critic_llm, etc.)
- `metadata`: Informations supplémentaires

#### Fonction `discover_local_models()`

**Sources de découverte** :
1. **models.json** : Catalogue centralisé
2. **Manifests Ollama** : Fichiers manifests dans store
3. **API Live** : `GET /api/tags` modèles chargés
4. **Filesystem** : Scan répertoires configurés

**Algorithme de fusion** :
- Normalisation noms avec alias
- Priorité disponibilité vérifiée
- Agrégation métadonnées
- Classification backend automatique

### 4. Intégration Backtest (`agents/integration.py`)

#### Fonction `create_orchestrator_with_backtest()`

**Paramètres clés** :
- `strategy_name`: Nom stratégie ("ema_cross", etc.)
- `data`: DataFrame OHLCV
- `llm_config`: Configuration LLM
- `role_model_config`: Attribution modèles par rôle
- `use_walk_forward`: Validation anti-overfitting
- `max_iterations`: Limite itérations
- `initial_capital`: Capital départ

**Création orchestrateur** :
1. Validation période données (min 180 jours pour walk-forward)
2. Extraction specs paramètres stratégie
3. Configuration callback backtest
4. Construction `OrchestratorConfig`
5. Instanciation `Orchestrator`

#### Fonction `run_backtest_for_agent()`

**Transformation données** :
- Normalisation métriques (pct → frac)
- Calcul equity curve (tronquée si >10k points)
- Extraction trades (limitée si >1000)
- Ajout run_id pour corrélation

**Métriques retournées** :
```python
AgentBacktestMetrics = TypedDict('AgentBacktestMetrics', {
    'sharpe_ratio': float,
    'sortino_ratio': float,
    'total_return': float,
    'max_drawdown': float,
    'win_rate': float,
    'profit_factor': float,
    'total_trades': int,
    'sqn': float,
    'calmar_ratio': float,
    'recovery_factor': float,
    'equity_curve': Optional[List[float]],
    'trades': Optional[List[Dict[str, Any]]],
    'run_id': str,
})
```

## Flux de Données Détaillés

### 1. Flux Normal (Optimisation LLM)

```
1. UI/CLI → create_orchestrator_with_backtest()
   ↓
2. Validation stratégie + données
   ↓
3. LLMConfig → create_llm_client() → OllamaClient()
   ↓
4. Orchestrator.run() → AnalystAgent
   ↓
5. AnalystAgent.chat() → analyse métriques backtest
   ↓
6. OllamaClient.chat() → POST /api/chat
   ↓
7. Ollama daemon → génération réponse analyse
   ↓
8. Parsing LLMResponse → extraction insights
   ↓
9. StrategistAgent → proposition nouveaux paramètres
   ↓
10. on_backtest_needed() → run_backtest_for_agent()
    ↓
11. BacktestEngine.run() → calculs stratégie
    ↓
12. Métriques → retour agents → évaluation CriticAgent
    ↓
13. Validation/itération jusqu'à convergence
```

### 2. Flux avec Gestion GPU

```
Session optimisation LLM active...
    ↓
StrategistAgent propose paramètres
    ↓
with gpu_compute_context("deepseek-r1:32b"):
    ↓
    GPUMemoryManager.unload()
    → POST /api/generate (keep_alive=0)
    → LLM déchargé GPU (logs: "💾 LLM déchargé: deepseek-r1:32b (150ms)")
    ↓
    BacktestExecutor → BacktestEngine.run()
    → Calculs NumPy/CuPy intensifs (GPU libre)
    ↓
GPUMemoryManager.reload()
    → POST /api/generate (warmup_prompt)
    → LLM rechargé (logs: "🔄 LLM rechargé: deepseek-r1:32b (8500ms)")
    ↓
CriticAgent évalue résultats
    ↓
Itération suivante...
```

### 3. Flux Découverte Modèles

```
discover_local_models()
    ↓
1. load_models_json() → C:\AI\models\catalog\models.json
   → Extraction ollama_models[], huggingface_models[]
    ↓
2. _discover_from_ollama_manifests() → scan C:\AI\ollama\models\manifests\
   → Parsing noms depuis structure registry.ollama.ai/library/model/tag
    ↓
3. _discover_from_live_ollama() → GET /api/tags
   → Liste modèles actuellement chargés + métadonnées
    ↓
4. _discover_from_generic_roots() → scan K:\models, L:\models
   → Détection fichiers .gguf, .safetensors, config.json
    ↓
5. Fusion et normalisation
   → Résolution alias (ex: "deepseek-r1-14b-local" → "deepseek-r1-distill:14b")
   → Classification backend + role_hints
    ↓
ModelInventory complet
    ↓
UI model_selector → affichage avec filtres catégorie
```

## Gestion d'Erreurs et Robustesse

### 1. Timeouts Adaptatifs

**Détection modèles reasoning** :
```python
def _is_reasoning_model(model_name: str) -> bool:
    reasoning_patterns = [
        "deepseek-r1", "qwq", "o1", "o3", "r1", "reasoning"
    ]
    return any(pattern in model_name.lower() for pattern in reasoning_patterns)
```

**Application timeout** :
- **Standard** : timeout configuré (60s par défaut)
- **Reasoning** : 900s (15 minutes)
- **Logging** : Avertissement explicite pour modèles lents

### 2. Fallback API

**Stratégie** :
- **Primaire** : `/api/chat` (conversations multi-messages)
- **Déclencheur fallback** : Erreur 404 sur /api/chat
- **Format fallback** : Conversion messages → prompt simple
- **Endpoint** : `POST /api/generate`

**Conversion messages** :
```python
def _messages_to_prompt(self, messages, json_mode) -> str:
    lines = []
    for msg in messages:
        role = msg.role or "user"
        if role == "system":
            label = "System"
        elif role == "assistant":
            label = "Assistant"
        else:
            label = "User"
        lines.append(f"{label}: {msg.content}")
    if json_mode:
        lines.append("System: Respond with valid JSON only.")
    lines.append("Assistant:")
    return "\n".join(lines)
```

### 3. Retry Logic

**Configuration** :
- **Max retries** : 3 par défaut
- **Backoff** : Exponentiel (1s, 2s, 4s...)
- **Erreurs couvertes** :
  - `httpx.TimeoutException`
  - Erreurs réseau/connexion
  - Erreurs serveur 5xx

**Logging détaillé** :
- Tentative actuelle / max
- Temps écoulé
- Raison retry

### 4. Validation Période

**Règle walk-forward** :
- **Minimum** : 180 jours (6 mois)
- **Calcul** : `(end - start).days`
- **Désactivation auto** : Si période insuffisante
- **Message** : Avertissement explicite avec durée calculée

## Configuration et Environnement

### Variables d'Environnement

```bash
# Ollama Core
OLLAMA_HOST=http://127.0.0.1:11434          # Host serveur Ollama
OLLAMA_MODELS=C:\AI\ollama\models           # Store modèles local

# Catalogue Modèles
MODELS_JSON_PATH=C:\AI\models\catalog\models.json  # Catalogue central
MODEL_LIBRARY_ROOTS=K:\models;L:\models     # Bibliothèques additionnelles
HUGGINGFACE_ARCHIVE_ROOT=L:\models          # Archive HuggingFace

# GPU et Performance
UNLOAD_LLM_DURING_BACKTEST=true             # Gestion mémoire GPU
CUDA_VISIBLE_DEVICES=0                      # Pinning GPU spécifique

# Logging et Debug
BACKTEST_LOG_LEVEL=INFO                     # Niveau logging
BACKTEST_GPU_ID=0                          # GPU par défaut
```

### Chemins Résolus (utils/model_loader.py)

**Fonction `get_ollama_models_root()`** :
- Candidats : C:\AI\ollama\models, K:\models, D:\models\ollama (legacy)
- Priorité : Contemporain (C:) > Bibliothèque (K:) > Legacy (D:)
- Fallback : Premier existant

**Fonction `get_models_json_path()`** :
- Candidats : C:\AI\models\catalog\models.json, D:\models\models.json
- Priorité : Contemporain > Legacy
- Création auto : Si aucun n'existe, retourne premier candidat

**Fonction `get_model_library_roots()`** :
- Valeur : K:\models, L:\models, C:\AI\models\library
- Format : Séparé par ";"
- Validation : Existence vérifiée

### Mapping Alias Modèles

```python
MODEL_NAME_ALIASES = {
    # DeepSeek
    "deepseek-r1-14b-local": "deepseek-r1-distill:14b",
    "deepseek-r1-14b-local:latest": "deepseek-r1-distill:14b",

    # Qwen
    "qwen3-coder-40b-local": "qwen3-coder:30b",
    "qwen3-coder-next-40b-q3_k_xl": "qwen3-coder:30b",
    "qwen3-30b-a3b": "qwen3-30b-a3b:q4_k_m",

    # Autres
    "llama3.3-70b-2gpu": "llama3.3:70b-instruct-q4_K_M",
    "llama3.3-70b-optimized": "llama3.3:70b-instruct-q4_K_M",
    "nemotron-cascade-14b-local": "nemotron-cascade-14b-local",
    "alia-40b-local": "alia-40b-local",
}
```

## Métriques et Observabilité

### Métriques Collectées

**Par requête LLM** :
- `prompt_tokens`: Tokens dans le prompt
- `completion_tokens`: Tokens générés
- `total_tokens`: Somme prompt + completion
- `latency_ms`: Temps total requête

**Cumulés par client** :
- `total_tokens`: Total tokens consommés
- `total_requests`: Nombre requêtes
- `provider`: Fournisseur (OLLAMA)
- `model`: Modèle utilisé

**GPU Memory Management** :
- `unload_time_ms`: Temps déchargement
- `reload_time_ms`: Temps rechargement
- `context_size`: Nombre messages contexte

### Logging Structuré

**Spans de traçage** :
```python
with trace_span(logger, "agent_backtest", strategy=strategy_name):
    # Exécution tracée
    pass
```

**Run IDs** :
- Génération : `generate_run_id()` (format UUID court)
- Propagation : Tous composants d'une session
- Corrélation : Logs groupés par run_id

**Niveaux de log** :
- `INFO`: Opérations normales (requêtes LLM, résultats)
- `WARNING`: Erreurs récupérables (timeout, indisponibilité)
- `ERROR`: Échecs définitifs
- `DEBUG`: Détails techniques (payloads, métriques)

### Métriques d'Observabilité

**Performance** :
- Latence moyenne par modèle
- Taux succès requêtes
- Taux retry par erreur

**Utilisation** :
- Tokens consommés par jour/session
- Modèles populaires
- Temps GPU unload/reload

## Points d'Extension et Maintenance

### 1. Ajout Nouveaux Modèles

**Étapes** :
1. **Alias** : Ajouter dans `MODEL_NAME_ALIASES`
2. **Reasoning** : Patterns dans `_is_reasoning_model()`
3. **Métadonnées** : Entrée dans models.json
4. **Role hints** : Patterns dans `_role_hints_for_name()`

**Exemple** :
```python
# Dans model_loader.py
MODEL_NAME_ALIASES["nouveau-modele"] = "nouveau-modele:q4_k_m"

# Dans model_discovery.py
if "nouveau" in lowered:
    hints.add("builder_llm")
```

### 2. Nouvelles APIs Ollama

**Extension client** :
```python
def nouvelle_fonction(self) -> Resultat:
    url = f"{self.config.ollama_host}/api/nouvelle"
    # Implémentation avec retry/fallback
```

**Fallback chains** :
- Tester nouvelle API
- Fallback vers API existante
- Logging dégradation

### 3. Optimisations Performance

**Cache modèles** :
- `ModelInventory` avec TTL
- Invalidation sur changements

**Connexions HTTP** :
- Pool de connexions httpx
- Keep-alive pour sessions longues

**Streaming avancé** :
- Bufferisation tokens
- Traitement parallèle chunks

## Tests et Validation

### Tests Unitaires

**Client LLM** (`tests/test_llm_client.py`) :
- Mock responses API
- Timeout adaptatif
- Retry logic
- Parsing JSON

**Gestion GPU** (`tests/test_ollama_manager.py`) :
- Context manager
- États mémoire
- Métriques unload/reload

**Découverte** (`tests/test_model_discovery.py`) :
- Scan répertoires
- Fusion modèles
- API live mocking

### Tests d'Intégration

**Flux complet** :
- CLI → Orchestrateur → Backtest
- GPU management réel
- Modèles Ollama live

**Performance** :
- Métriques latence
- Utilisation mémoire
- Taux succès

### Tests de Robustesse

**Erreurs réseau** :
- Déconnexion Ollama
- Timeout réels
- Recovery automatique

**États dégradés** :
- Modèles corrompus
- GPU memory full
- API incompatibles

## Déploiement et Production

### Configuration Production

**Variables d'environnement** :
```bash
# Serveur dédié
OLLAMA_HOST=http://ollama-prod:11434

# GPU pinning
CUDA_VISIBLE_DEVICES=0,1

# Logging structuré
BACKTEST_LOG_LEVEL=WARNING
```

**Monitoring** :
- Métriques Prometheus
- Alertes sur échecs
- Dashboards Grafana

### Scaling

**Multi-GPU** :
- Distribution modèles selon VRAM
- Load balancing requêtes
- Memory pooling

**Multi-instances** :
- Orchestrateurs parallèles
- Coordination via Redis
- Résultats agrégation

### Sécurité

**Isolation** :
- Containers Ollama dédiés
- Network policies
- API authentication

**Audit** :
- Logs requêtes LLM
- Métriques utilisation
- Alertes anomalies

## Conclusion

L'intégration Ollama dans backtest_core_v2 constitue une architecture robuste et extensible pour l'optimisation multi-agents de stratégies de trading. Les abstractions unifiées permettent une évolution facile vers de nouveaux fournisseurs LLM, tandis que la gestion spécialisée GPU assure des performances optimales.

**Points forts** :
- Abstraction propre LLMClient/OllamaClient
- Gestion mémoire GPU intelligente
- Découverte automatique modèles
- Robustesse erreurs (retry, fallback, timeout adaptatif)
- Observabilité complète (logs, métriques, tracing)

**Évolutivité** :
- Support multi-modèles par rôle
- Extension facile nouveaux modèles/APIs
- Architecture modulaire pour scaling

Cette intégration permet des optimisations trading avancées avec des modèles de langage de dernière génération, tout en maintenant la stabilité et les performances du système de backtest.</content>
<parameter name="filePath">d:\backtest_core_v2\OLLAMA_INTEGRATION_REPORT.md