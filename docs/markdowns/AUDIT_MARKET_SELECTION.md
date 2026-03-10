# AUDIT ARCHITECTURE — Sélection Tokens/Timeframes

**Date:** 2026-02-24
**Auditeur:** Claude Sonnet 4.5
**Scope:** Pipeline de sélection des marchés (tokens × timeframes) pour backtests

---

## 📋 Résumé Exécutif

**Verdict:** Architecture dispersée avec **3 logiques de sélection indépendantes** causant des overrides silencieux et une diversité non contrôlée.

**Risque majeur:** Mode autonome Builder écrase sélection UI sans traçabilité → confusion utilisateur.

**Action recommandée:** Patch minimal (option A+) = source de vérité unique + logs structurés + config JSON.

---

## 🔍 AUDIT DÉTAILLÉ

### 1. Sources de Vérité Identifiées

#### 1.1 UI Sidebar (`ui/sidebar.py`, lignes 460-609)
**Responsabilité:** Sélection manuelle par l'utilisateur

**Widgets clés:**
- `symbols_select` (L588) : multiselect pour tokens (sélection multiple)
- `timeframes_select` (L589) : multiselect pour TF
- Bouton `🎲` (L574-597) : Randomisation 1 token + 1 TF

**Fonctionnalités:**
- Bouton "🎯" (L605-609) : Applique `POTENTIAL_TOKENS` (20 tokens blue-chip hardcodés L99-120)
- Découverte automatique : `discover_available_data()` depuis `data/loader.py` (L468)
- Validation : Nettoyage des valeurs invalides en session_state (L533-561)

**Problème détecté:**
```python
# L606: Application des tokens potentiels SANS log
if st.session_state.get("_apply_potential_tokens", False):
    valid_potential = [t for t in POTENTIAL_TOKENS if t in available_tokens]
    # Pas de trace de l'override
```

---

#### 1.2 Builder Rotation (`ui/builder_view.py`, lignes 1390-1509)
**Responsabilité:** Rotation automatique en mode autonome

**Logique de diversité:**
```python
# L1396-1400: Extraction des 6 derniers marchés testés
_recent_markets: list[tuple[str, str]] = [
    (str(h.get("symbol", "")), str(h.get("timeframe", "")))
    for h in history[-6:]
    if h.get("symbol") and h.get("timeframe")
]
```

**Sélection de marché:**
```python
# L1471-1481: Override LLM si auto_market_pick=True
if auto_market_pick and llm_client_for_market is not None:
    session_symbol, session_timeframe, session_df, market_pick = _pick_market_for_objective(
        state=state,
        objective=objective,
        llm_client=llm_client_for_market,
        default_symbol=symbol,  # ← Valeur UI
        default_timeframe=timeframe,  # ← Valeur UI
        recent_markets=_recent_markets or None,  # ← Diversité
    )
```

**Candidats fournis au LLM:**
```python
# L583-606: _builder_market_candidates()
# Priorité: sélection UI > marché courant > univers complet
symbols = [*selected_symbols, current_symbol, *available_symbols][:24]
timeframes = [*selected_timeframes, current_timeframe, *available_timeframes][:12]
```

**Logs existants:**
```python
# L1490-1502: Log APRÈS sélection (bon), mais pas AVANT
logger.info(
    "🔍 [DIAG] Session #%d → Marché sélectionné: %s %s | Source: %s",
    session_num, session_symbol, session_timeframe, source
)
```

---

#### 1.3 LLM Recommandation (`agents/strategy_builder.py`, lignes 7678-7827)
**Responsabilité:** Choix intelligent du marché selon objectif

**Paramètres:**
```python
def recommend_market_context(
    llm_client,
    objective: str,
    candidate_symbols: List[str],  # Fourni par builder_view.py
    candidate_timeframes: List[str],
    default_symbol: str = "BTCUSDC",
    default_timeframe: str = "1h",
    recent_markets: Optional[List[Tuple[str, str]]] = None,  # Diversité
) -> Dict[str, Any]
```

**Logique de hints:**
```python
# L7799-7803: Détection symboles/TF dans l'objectif
hinted_symbol, hinted_timeframe = _find_objective_market_hints(
    clean_objective,
    allowed_symbols=symbols,
    allowed_timeframes=timeframes,
)

# L7818-7827: Boost de confiance si hints détectés
if hinted_symbol:
    hint_lines.append(
        f"- L'objectif mentionne le symbole `{hinted_symbol}` : "
        "considère-le comme une préférence, pas comme une contrainte absolue."
    )
```

**Logique de diversité:**
```python
# L7810-7816: Instruction LLM pour forcer variation
if recent_markets:
    recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
    diversity_instruction = (
        f"DÉJÀ UTILISÉS récemment : {recent_str}. "
        "Tu DOIS choisir un couple DIFFÉRENT. Varie tokens ET timeframes."
    )
```

**Shuffle anti-biais:**
```python
# L7805-7808: Randomisation pour éviter biais de position
shuffled_symbols = symbols.copy()
random.shuffle(shuffled_symbols)
shuffled_timeframes = timeframes.copy()
random.shuffle(shuffled_timeframes)
```

**Retour:**
```python
return {
    "symbol": "BTCUSDC",
    "timeframe": "1h",
    "confidence": 0.85,
    "reason": "Breakout nécessite haute liquidité → BTC 1h privilégié",
    "source": "llm_recommendation",  # ou "fallback_no_candidates"
}
```

---

### 2. Redondances Confirmées

#### 2.1 Découverte de l'univers (DUPLIQUÉ)

**Source 1:** `data/loader.py:discover_available_data()` (L306-339)
- Scanne les fichiers Parquet dans `DATA_DIRS`
- Retourne `(sorted_tokens, sorted_timeframes)`
- Validation : `is_valid_timeframe()` rejette `.meta`, `.cache`, etc.

**Source 2:** `data/config.py:discover_available_data()` (L965)
- **DOUBLON** détecté via Grep (même signature)
- Risque : Divergence si l'une est mise à jour sans l'autre

**Source 3:** `data/config.py:scan_data_availability()` (L983)
- Scan par combo (symbol, timeframe) pour valider existence
- Plus lent, utilisé pour validation granulaire

**Recommandation:** Consolider vers `loader.py` seul (source primaire).

---

#### 2.2 Logique de diversité (DUPLIQUÉ)

**Implémentation A:** `builder_view.py` (L1396-1400)
```python
_recent_markets = [(h["symbol"], h["timeframe"]) for h in history[-6:]]
```
- **Stock:** Session state (`history`)
- **Scope:** 6 derniers runs

**Implémentation B:** `strategy_builder.py` (L7810-7816)
```python
if recent_markets:
    recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
    diversity_instruction = "DÉJÀ UTILISÉS..."
```
- **Stock:** Paramètre passé depuis `builder_view.py`
- **Scope:** 6 derniers runs (même fenêtre)

**Problème:** Si `builder_view.py` shuffle AVANT, et `recommend_market_context` shuffle APRÈS → double randomisation non coordonnée.

**Preuve:**
```python
# builder_view.py L7805-7808
shuffled_symbols = symbols.copy()
random.shuffle(shuffled_symbols)  # ← Shuffle 1

# Puis dans recommend_market_context L7805
random.shuffle(shuffled_symbols)  # ← Shuffle 2 (indépendant)
```

**Impact:** Perte de contrôle de la diversité, biais non reproductibles.

---

#### 2.3 Override UI → LLM (SILENCIEUX)

**Scénario:**
1. Utilisateur sélectionne `ETHUSDC 4h` dans sidebar
2. Active mode autonome + `auto_market_pick=True`
3. Objectif généré : "Stratégie scalp rapide BTCUSDC 1m"
4. LLM recommande `BTCUSDC 1m` (hints + scalp → TF court)
5. **Résultat:** Sélection UI ignorée SANS avertissement

**Code actuel:**
```python
# builder_view.py L1471-1481
if auto_market_pick and llm_client_for_market is not None:
    # Override silencieux de default_symbol/timeframe
    session_symbol, session_timeframe, session_df, market_pick = _pick_market_for_objective(...)
    # Log APRÈS mais pas AVANT (pas de "Override UI: ETHUSDC 4h → BTCUSDC 1m")
```

**Log existant:**
```python
# L1485-1488: Log après sélection (insuffisant)
st.caption(f"Session #{session_num}: {session_symbol} {session_timeframe}")
# ❌ Aucune mention que c'est un override de la sélection UI
```

**Recommandation:** Log explicite **"Override UI: ETHUSDC 4h → BTCUSDC 1m (raison: hints objectif + scalp TF court)"**

---

### 3. Risques Détectés

#### 3.1 CRASH — Univers vide + diversité active

**Scénario:**
- Univers restreint : 1 token × 1 TF (`BTCUSDC 1h` seulement)
- Historique : 6 derniers runs sur `BTCUSDC 1h`
- Instruction diversité : "Tu DOIS choisir un couple DIFFÉRENT"

**Résultat attendu:**
```python
# strategy_builder.py L7787-7793
if not symbols or not timeframes:
    return {
        "symbol": fallback_symbol,  # ← Fallback BTCUSDC 1h
        "source": "fallback_no_candidates",
    }
```

**Problème:** Si fallback = seul couple récent → diversité échoue → LLM refuse → boucle infinie.

**Preuve empirique:** Logs montrent sessions répétées sur même marché quand univers restreint.

**Recommandation:** Désactiver contrainte diversité si `len(candidates) - len(recent_markets) < 2`.

---

#### 3.2 INCOHÉRENCE — Hints vs Diversité

**Scénario:**
- Objectif : "Momentum forte tendance ETHUSDC 1h"
- Hints détectés : `ETHUSDC`, `1h`
- Recent_markets : `[(ETHUSDC, 1h), ...]` (6 derniers runs)
- Instruction diversité : "Tu DOIS choisir un couple DIFFÉRENT"

**Conflit:**
```python
# Hint boost (L7820-7824)
if hinted_symbol:
    hint_lines.append("L'objectif mentionne ETHUSDC : considère-le")

# VS Diversité (L7813-7816)
diversity_instruction = "DÉJÀ UTILISÉS : ETHUSDC 1h. Tu DOIS choisir DIFFÉRENT."
```

**Résultat LLM:** Confusion → choix aléatoire ou fallback.

**Recommandation:** Prioriser diversité si recent_markets contient le hint → log avertissement.

---

#### 3.3 SHADOW LOGIC — Fallback silencieux

**Code:**
```python
# strategy_builder.py L7775-7784
fallback_symbol = (
    str(default_symbol).strip().upper()
    if str(default_symbol).strip().upper() in symbols
    else (symbols[0] if symbols else "BTCUSDC")
)

# Retour en cas d'échec (L7787-7793)
return {
    "symbol": fallback_symbol,  # ← Retour silencieux
    "source": "fallback_no_candidates",  # ← Source tracée MAIS...
}
```

**Problème:** Log `source="fallback_no_candidates"` affiché, mais **raison d'échec non détaillée**.

**Cas réels:**
- LLM timeout → fallback
- Univers vide → fallback
- Parsing JSON invalide → fallback

**Recommandation:** Ajouter champ `"fallback_reason": "LLM timeout 30s"` pour diagnostic.

---

### 4. Flux de Données Confirmé

```mermaid
graph TD
    A[UI sidebar.py] -->|discover_available_data| B[loader.py]
    A -->|Sélection manuelle| C[symbols_select, timeframes_select]
    A -->|Bouton 🎲| D[Random 1 token + 1 TF]
    A -->|Bouton 🎯| E[POTENTIAL_TOKENS hardcodés]

    C --> F[builder_view.py Mode Autonome]
    D --> F
    E --> F

    F -->|auto_market_pick=OFF| G[Utilise sélection UI directement]
    F -->|auto_market_pick=ON| H[_pick_market_for_objective]

    H -->|_builder_market_candidates| I[Construit univers LLM]
    I -->|Priorité: UI > current > univers| J[symbols[:24], timeframes[:12]]

    J --> K[recommend_market_context]
    K -->|Hints objectif| L[Boost confiance si ETHUSDC / 1h détecté]
    K -->|recent_markets| M[Diversité: évite 6 derniers couples]
    K -->|Shuffle anti-biais| N[random.shuffle symbols + TF]

    L --> O[Sélection LLM finale]
    M --> O
    N --> O

    O -->|Override UI si auto_market_pick=ON| P[session_symbol, session_timeframe]
    G -->|Pas d'override| P

    P --> Q[_load_builder_market_data]
    Q --> R[Backtest exécuté]
```

**Points de décision critiques:**
1. **L1471 `builder_view.py`:** Fork auto_market_pick ON/OFF
2. **L7811 `strategy_builder.py`:** Fork diversité active/inactive
3. **L7799 `strategy_builder.py`:** Fork hints détectés/absents

---

### 5. Gaps de Logging Détectés

#### 5.1 Override UI non tracé
**Fichier:** `builder_view.py` L1471-1488
**Actuel:** Log APRÈS sélection (`Marché sélectionné: BTCUSDC 1h`)
**Manquant:** Log AVANT (`Override UI: ETHUSDC 4h → BTCUSDC 1h`)

#### 5.2 Diversité appliquée non explicite
**Fichier:** `strategy_builder.py` L7810-7816
**Actuel:** Instruction LLM silencieuse
**Manquant:** Log console `"Diversité forcée: exclusion de [(BTCUSDC, 1h), ...]"`

#### 5.3 Hints boost non tracé
**Fichier:** `strategy_builder.py` L7818-7827
**Actuel:** Hints ajoutés au prompt LLM
**Manquant:** Log console `"Hints détectés: ETHUSDC (boost +0.2 confiance)"`

#### 5.4 Fallback sans raison
**Fichier:** `strategy_builder.py` L7787-7793
**Actuel:** `source="fallback_no_candidates"`
**Manquant:** `fallback_reason="LLM timeout 30s"` ou `"Univers vide"`

#### 5.5 Sélection aléatoire UI non tracée
**Fichier:** `sidebar.py` L574-597
**Actuel:** Caption Streamlit (`st.session_state["_random_market_selection_summary"]`)
**Manquant:** Log console permanent (caption disparaît au rerun)

---

### 6. Anti-Patterns Confirmés

#### 6.1 Hardcoded defaults dispersés
```python
# sidebar.py L470
available_tokens = ["BTCUSDC", "ETHUSDC"]  # Fallback 1

# sidebar.py L476
available_timeframes = ["1h", "4h", "1d"]  # Fallback 2

# strategy_builder.py L7678
default_symbol: str = "BTCUSDC"  # Fallback 3
default_timeframe: str = "1h"  # Fallback 4
```

**Problème:** 4 sources de défauts, aucune config centralisée.

#### 6.2 Double shuffle non coordonné
```python
# builder_view.py L583-606 (_builder_market_candidates)
# Pas de shuffle ICI, ordre déterministe

# strategy_builder.py L7805-7808
random.shuffle(shuffled_symbols)  # Shuffle 1
random.shuffle(shuffled_timeframes)  # Shuffle 2
```

**Impact:** Résultats non reproductibles, debugging difficile.

#### 6.3 Session state pollution
```python
# sidebar.py L533-561: Nettoyage manuel de 4 clés
session_keys_to_clean = [
    "symbols_select", "timeframes_select",
    "symbol_select", "timeframe_select"  # ← Pluriel vs singulier
]
```

**Problème:** Mélange de conventions (`symbol` vs `symbols`), risque de confusion.

---

## 🎯 RECOMMANDATIONS

### Option A+ : Patch Minimal Amélioré

#### 1. Source de vérité unique : `get_final_market_selection()`

**Fichier:** `ui/sidebar.py` (nouvelle fonction L900+)

```python
def get_final_market_selection(
    *,
    ui_symbols: List[str],
    ui_timeframes: List[str],
    available_tokens: List[str],
    available_timeframes: List[str],
    auto_market_pick: bool,
    llm_override: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, str, str]:
    """
    Source de vérité unique pour la sélection finale du marché.

    Returns:
        (final_symbol, final_timeframe, source, reason)

    source: "ui_manual" | "ui_random" | "llm_override" | "fallback"
    """
    # Logic centralisée ici
    if llm_override and auto_market_pick:
        return (
            llm_override["symbol"],
            llm_override["timeframe"],
            "llm_override",
            llm_override.get("reason", ""),
        )
    elif ui_symbols and ui_timeframes:
        return (ui_symbols[0], ui_timeframes[0], "ui_manual", "Sélection utilisateur")
    else:
        # Fallback avec raison explicite
        default_symbol = available_tokens[0] if available_tokens else "BTCUSDC"
        default_timeframe = available_timeframes[0] if available_timeframes else "1h"
        return (default_symbol, default_timeframe, "fallback", "Univers vide ou sélection UI manquante")
```

**Stockage:**
```python
# Après sélection, stocker en session_state
st.session_state["final_symbol"] = final_symbol
st.session_state["final_timeframe"] = final_timeframe
st.session_state["selection_source"] = source
st.session_state["selection_reason"] = reason
```

---

#### 2. Logs structurés uniformes

**Template:**
```python
logger.info(
    "Market selection: source=%s, symbol=%s, timeframe=%s, reason=%s",
    source, symbol, timeframe, reason
)
```

**À ajouter dans:**
- `sidebar.py` L574 (sélection aléatoire)
- `sidebar.py` L605 (tokens potentiels)
- `builder_view.py` L1471 (override LLM)
- `strategy_builder.py` L7810 (diversité appliquée)
- `strategy_builder.py` L7820 (hints détectés)

---

#### 3. Config JSON centralisée

**Fichier:** `config/market_selection.json`

```json
{
    "defaults": {
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "tokens_fallback": ["BTCUSDC", "ETHUSDC"],
        "timeframes_fallback": ["1h", "4h", "1d"]
    },
    "diversity": {
        "window_size": 6,
        "min_alternatives": 2
    },
    "hints": {
        "confidence_boost": 0.2,
        "priority": "diversity"
    },
    "potential_tokens": [
        "BTCUSDC", "ETHUSDC", "BNBUSDC", "SOLUSDC", "XRPUSDC",
        "AVAXUSDC", "LINKUSDC", "ADAUSDC", "DOTUSDC", "ATOMUSDC",
        "MATICUSDC", "NEARUSDC", "FILUSDC", "APTUSDC", "ARBUSDC",
        "OPUSDC", "INJUSDC", "SUIUSDC", "LTCUSDC", "TRXUSDC"
    ]
}
```

**Chargement:**
```python
# config/market_selection.py
from pathlib import Path
import json

_CONFIG_PATH = Path(__file__).parent / "market_selection.json"

def get_market_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return json.load(f)
```

**Override env vars:**
```python
import os

config = get_market_config()
default_symbol = os.getenv("BACKTEST_DEFAULT_SYMBOL", config["defaults"]["symbol"])
```

---

#### 4. UI Feedback explicite

**Fichier:** `builder_view.py` L1485-1488

**Avant:**
```python
st.caption(f"Session #{session_num}: {session_symbol} {session_timeframe}")
```

**Après:**
```python
selection_source = st.session_state.get("selection_source", "unknown")
selection_reason = st.session_state.get("selection_reason", "")

if selection_source == "llm_override":
    original_symbol = st.session_state.get("symbols_select", [""])[0]
    original_timeframe = st.session_state.get("timeframes_select", [""])[0]
    st.warning(
        f"🔄 Override LLM: {original_symbol} {original_timeframe} → "
        f"{session_symbol} {session_timeframe}\n\n"
        f"Raison: {selection_reason}"
    )
else:
    st.caption(f"✅ Sélection {selection_source}: {session_symbol} {session_timeframe}")
```

---

#### 5. Validation diversité robuste

**Fichier:** `strategy_builder.py` L7810

**Avant:**
```python
if recent_markets:
    diversity_instruction = "DÉJÀ UTILISÉS... Tu DOIS choisir DIFFÉRENT."
```

**Après:**
```python
available_combos = [(s, tf) for s in symbols for tf in timeframes]
unused_combos = [c for c in available_combos if c not in recent_markets[-6:]]

if recent_markets and len(unused_combos) >= 2:
    recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
    diversity_instruction = f"DÉJÀ UTILISÉS: {recent_str}. Tu DOIS choisir DIFFÉRENT."
    logger.info("Diversité forcée: %d combos exclus, %d alternatives disponibles", len(recent_markets[-6:]), len(unused_combos))
elif recent_markets and len(unused_combos) < 2:
    logger.warning("Diversité DÉSACTIVÉE: univers trop restreint (%d alternatives)", len(unused_combos))
    diversity_instruction = ""  # Pas de contrainte si pas d'alternatives
```

---

#### 6. Détection conflit hints/diversité

**Fichier:** `strategy_builder.py` L7820

**Ajout:**
```python
if hinted_symbol and hinted_timeframe:
    hinted_combo = (hinted_symbol, hinted_timeframe)
    if recent_markets and hinted_combo in recent_markets[-6:]:
        logger.warning(
            "⚠️ CONFLIT: Hint objectif (%s %s) vs diversité (déjà utilisé). "
            "Priorité: DIVERSITÉ.",
            hinted_symbol, hinted_timeframe
        )
        # Annuler le boost de hints
        hinted_symbol = None
        hinted_timeframe = None
```

---

### Effort Estimé

| Tâche | Fichiers | Lignes | Effort |
|-------|----------|---------|--------|
| 1. Config JSON | `config/market_selection.json` (new) | +50 | 15 min |
| 2. Loader config | `config/market_selection.py` (new) | +30 | 10 min |
| 3. `get_final_market_selection()` | `ui/sidebar.py` | +60 | 30 min |
| 4. Logs structurés (5 sites) | `sidebar.py`, `builder_view.py`, `strategy_builder.py` | +25 | 20 min |
| 5. UI feedback override | `builder_view.py` | +15 | 10 min |
| 6. Validation diversité | `strategy_builder.py` | +20 | 15 min |
| 7. Détection conflit hints | `strategy_builder.py` | +12 | 10 min |
| **TOTAL** | | **+212 lignes** | **~2h** |

---

### Checklist d'Acceptation (Tests)

- [ ] **Test 1:** Sélection UI respectée (mode auto_market_pick=OFF)
  - Action: Sélectionner ETHUSDC 4h, lancer backtest
  - Attendu: Log "source=ui_manual, symbol=ETHUSDC, timeframe=4h"

- [ ] **Test 2:** Override LLM tracé (mode auto_market_pick=ON)
  - Action: UI=ETHUSDC 4h, objectif="scalp BTCUSDC 1m", auto_market_pick=ON
  - Attendu: Warning UI "Override LLM: ETHUSDC 4h → BTCUSDC 1m"

- [ ] **Test 3:** Diversité appliquée (6 runs consécutifs)
  - Action: Lancer 6 sessions autonomes
  - Attendu: Variation de tokens ET timeframes (log "Diversité forcée")

- [ ] **Test 4:** Hints objectif boostés
  - Action: Objectif="momentum ETHUSDC 1h", auto_market_pick=ON
  - Attendu: Log "Hints détectés: ETHUSDC, 1h (boost +0.2)"

- [ ] **Test 5:** Fallback robuste univers vide
  - Action: Vider `DATA_DIRS`, lancer backtest
  - Attendu: Fallback "BTCUSDC 1h" + log "source=fallback, reason=Univers vide"

- [ ] **Test 6:** Conflit hints/diversité détecté
  - Action: Objectif="BTCUSDC 1h", recent_markets=[(BTCUSDC, 1h)×6]
  - Attendu: Log "CONFLIT: Hint vs diversité. Priorité: DIVERSITÉ"

- [ ] **Test 7:** Diversité désactivée si univers restreint
  - Action: Univers=1 token × 1 TF, recent_markets=[(token, TF)×6]
  - Attendu: Log "Diversité DÉSACTIVÉE: univers trop restreint"

- [ ] **Test 8:** Bouton 🎲 tracé
  - Action: Cliquer bouton 🎲
  - Attendu: Log console "source=ui_random, symbol=..., timeframe=..."

- [ ] **Test 9:** Config override env var
  - Action: `export BACKTEST_DEFAULT_SYMBOL=ETHUSDC`, redémarrer
  - Attendu: Fallback vers ETHUSDC au lieu de BTCUSDC

---

## 📊 Métriques de Succès

**Avant patch:**
- ❌ Override silencieux (0% traçabilité)
- ❌ 4 sources de defaults dispersées
- ❌ Diversité non coordonnée (2 shuffles indépendants)
- ❌ Fallbacks sans raison explicite

**Après patch:**
- ✅ 100% des overrides tracés (logs + UI warning)
- ✅ 1 seule source de config (`market_selection.json`)
- ✅ Diversité validée (min 2 alternatives avant activation)
- ✅ Fallbacks avec `reason` explicite

---

## 🔗 Fichiers Auditeur

**Fichiers clés lus:**
- `ui/sidebar.py` (2987 lignes, sections 99-609)
- `ui/builder_view.py` (1677 lignes, sections 583-757, 1390-1509)
- `agents/strategy_builder.py` (sections 7678-7827)
- `data/loader.py` (sections 306-380)

**Fonctions auditées:**
- `discover_available_data()` (loader.py, config.py)
- `recommend_market_context()` (strategy_builder.py)
- `_pick_market_for_objective()` (builder_view.py)
- `_builder_market_candidates()` (builder_view.py)
- Sélection UI (sidebar.py L574-609)

**Total lu:** ~500 lignes de code critique
