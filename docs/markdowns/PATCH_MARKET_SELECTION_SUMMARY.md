# PATCH MARKET SELECTION — Résumé des Modifications

**Date:** 2026-02-24
**Scope:** Implémentation patch minimal (Option A+) suite à l'audit d'architecture

---

## 🎯 Objectif

Centraliser la logique de sélection tokens/timeframes, tracer tous les overrides, et améliorer la robustesse de la diversité.

---

## ✅ Modifications Réalisées

### 1. Configuration Centralisée

**Nouveau fichier:** `config/market_selection.json`
- Defaults : symbol, timeframe, fallbacks
- Diversité : window_size (6), min_alternatives (2)
- Hints : confidence_boost (0.2)
- Potential tokens : 20 tokens blue-chip

**Nouveau fichier:** `config/market_selection.py`
- Fonctions : `get_market_config()`, `get_default_symbol()`, etc.
- Cache config : chargement 1× par process
- Overrides env vars : `BACKTEST_DEFAULT_SYMBOL`, `BACKTEST_DEFAULT_TIMEFRAME`, `BACKTEST_DIVERSITY_WINDOW`

---

### 2. Source de Vérité Unique

**Fichier:** `ui/sidebar.py` (nouvelle fonction L447+)

```python
def get_final_market_selection(
    ui_symbols, ui_timeframes, available_tokens, available_timeframes,
    auto_market_pick, llm_override
) -> (symbol, timeframe, source, reason)
```

**Logique de priorité :**
1. Override LLM (si `auto_market_pick=True`)
2. Sélection UI manuelle
3. Fallback config centralisée

**Sources retournées :**
- `"llm_override"` : LLM a écrasé la sélection UI
- `"ui_manual"` : Sélection manuelle utilisateur
- `"ui_random"` : Bouton 🎲
- `"fallback"` : Univers vide ou sélection manquante

---

### 3. Logs Structurés (5 sites)

#### 3.1 Sélection aléatoire UI (`sidebar.py` L665+)

**Avant :**
```python
st.session_state["_random_market_selection_summary"] = f"🎲 Aléatoire: ..."
# Caption UI disparaît au rerun
```

**Après :**
```python
logger.info(
    "Market selection: source=ui_random, symbol=%s, timeframe=%s, strategy=%s (%s), reason=Bouton 🎲",
    random_symbol, random_timeframe, random_strategy, strategy_mode
)
# + Marqueur session_state["_random_market_applied"] = True
```

---

#### 3.2 Tokens potentiels (`sidebar.py` L697+)

**Ajout :**
```python
logger.info(
    "Market selection: source=ui_potential_tokens, added_count=%d, tokens=%s, reason=Bouton 🎯",
    len(added_tokens), ", ".join(added_tokens)
)
```

---

#### 3.3 Override LLM (`builder_view.py` L1471+)

**Avant :**
```python
st.caption(f"Session #{session_num}: {session_symbol} {session_timeframe}")
# Pas de mention d'override
```

**Après :**
```python
if is_override:
    st.warning(
        f"🔄 Override LLM: {symbol} {timeframe} → {session_symbol} {session_timeframe}\n"
        f"Raison: {reason}\nSource: {source} | Confidence: {confidence:.2f}"
    )
    logger.info(
        "Market selection: source=llm_override, original=%s %s, final=%s %s, reason=%s, confidence=%.2f",
        symbol, timeframe, session_symbol, session_timeframe, reason, confidence
    )
```

---

#### 3.4 Diversité (`strategy_builder.py` L7810+)

**Avant :**
```python
if recent_markets:
    diversity_instruction = "DÉJÀ UTILISÉS... Tu DOIS choisir DIFFÉRENT."
```

**Après :**
```python
# Validation : désactiver si trop peu d'alternatives
unused_combos = [c for c in available_combos if c not in recent_window]
min_alts = get_diversity_min_alternatives()  # Config centralisée (2)

if len(unused_combos) >= min_alts:
    diversity_instruction = "DÉJÀ UTILISÉS..."
    logger.info(
        "Market selection: diversity=ACTIVE, excluded_count=%d, alternatives=%d, recent=%s",
        len(recent_window), len(unused_combos), recent_str
    )
else:
    diversity_instruction = ""  # Désactivée
    logger.warning(
        "Market selection: diversity=DISABLED, reason=Univers restreint (%d alternatives < %d min)",
        len(unused_combos), min_alts
    )
```

**Impact :** Évite boucle infinie diversité sur univers restreint.

---

#### 3.5 Hints + Conflit diversité (`strategy_builder.py` L7820+)

**Avant :**
```python
if hinted_symbol:
    hint_lines.append("L'objectif mentionne...")
# Pas de détection de conflit avec recent_markets
```

**Après :**
```python
# Détection conflit hints vs diversité
if hinted_symbol and hinted_timeframe and recent_markets:
    hinted_combo = (hinted_symbol, hinted_timeframe)
    if hinted_combo in recent_markets[-6:]:
        logger.warning(
            "Market selection: CONFLICT hints vs diversity, hinted=%s %s (already in recent_markets), "
            "priority=diversity → hints IGNORED",
            hinted_symbol, hinted_timeframe
        )
        hinted_symbol = None  # Annuler hints
        hinted_timeframe = None

# Log hints détectés (si pas de conflit)
if hint_lines:
    boost = get_hints_confidence_boost()  # Config centralisée (0.2)
    logger.info(
        "Market selection: hints_detected=YES, symbol=%s, timeframe=%s, boost=+%.2f confidence",
        hinted_symbol or "NONE", hinted_timeframe or "NONE", boost
    )
```

**Impact :** Résout l'incohérence hints vs diversité, priorité explicite à la diversité.

---

### 4. Bugfix : UnboundLocalError 'random'

**Fichier:** `ui/sidebar.py` L1427

**Problème :**
```python
# L1427 (dans bloc conditionnel)
import random  # ← Import local
# L575 (plus haut dans la même fonction)
random_symbol = random.choice(...)  # ← Erreur: random pas encore assigné
```

**Cause :** Python voit `import random` local L1427 → traite `random` comme variable locale dans toute la fonction → L575 utilise `random` avant assignation.

**Solution :**
```python
# L1427: Suppression import local (déjà importé globalement L28)
# import random  ← SUPPRIMÉ
import time
```

---

## 📊 Métriques

| Métrique | Avant | Après | Impact |
|----------|-------|-------|--------|
| Sources de config dispersées | 4 (sidebar, strategy_builder × 2, defaults hardcodés) | 1 (`market_selection.json`) | ✅ Centralisé |
| Override LLM tracé | 0% (silencieux) | 100% (log + UI warning) | ✅ Traçabilité |
| Diversité validée | Non (boucle infinie possible) | Oui (min 2 alternatives) | ✅ Robustesse |
| Conflit hints/diversité | Non détecté | Détecté + résolu (priorité diversité) | ✅ Cohérence |
| Fallbacks sans raison | Oui (`source="fallback"` seulement) | Amélioré (`reason` explicite) | ✅ Diagnostic |
| Logs sélection UI | Partiel (caption Streamlit éphémère) | Complet (logs console permanents) | ✅ Auditabilité |

---

## 🧪 Tests d'Acceptation

### Test 1 : Sélection UI respectée (auto_market_pick=OFF)
```bash
# Action: Sélectionner ETHUSDC 4h dans sidebar, auto_market_pick=OFF
# Attendu: Log "source=ui_manual, symbol=ETHUSDC, timeframe=4h"
```

### Test 2 : Override LLM tracé (auto_market_pick=ON)
```bash
# Action: UI=ETHUSDC 4h, objectif="scalp BTCUSDC 1m", auto_market_pick=ON
# Attendu: UI warning "Override LLM: ETHUSDC 4h → BTCUSDC 1m"
# Attendu: Log "source=llm_override, original=ETHUSDC 4h, final=BTCUSDC 1m"
```

### Test 3 : Diversité appliquée (6 runs consécutifs)
```bash
# Action: Lancer 6 sessions autonomes avec auto_market_pick=ON
# Attendu: Variation tokens ET timeframes
# Attendu: Log "diversity=ACTIVE, excluded_count=6, alternatives=X"
```

### Test 4 : Diversité désactivée (univers restreint)
```bash
# Action: Univers = 1 token × 1 TF, recent_markets = [(token, TF) × 6]
# Attendu: Log "diversity=DISABLED, reason=Univers restreint (0 alternatives < 2 min)"
# Attendu: PAS d'instruction diversité dans prompt LLM
```

### Test 5 : Conflit hints vs diversité
```bash
# Action: Objectif="BTCUSDC 1h", recent_markets=[(BTCUSDC, 1h) × 6]
# Attendu: Log "CONFLICT hints vs diversity, hinted=BTCUSDC 1h, priority=diversity → hints IGNORED"
```

### Test 6 : Bouton 🎲 tracé
```bash
# Action: Cliquer bouton 🎲
# Attendu: Log "source=ui_random, symbol=..., timeframe=..., strategy=..."
# Attendu: Marqueur session_state["_random_market_applied"] = True
```

### Test 7 : Config override env var
```bash
# Action: export BACKTEST_DEFAULT_SYMBOL=ETHUSDC && redémarrer
# Attendu: Fallback vers ETHUSDC au lieu de BTCUSDC
```

### Test 8 : Hints détectés (pas de conflit)
```bash
# Action: Objectif="momentum ETHUSDC 1h", recent_markets=[(BTCUSDC, 4h) × 6]
# Attendu: Log "hints_detected=YES, symbol=ETHUSDC, timeframe=1h, boost=+0.20 confidence"
```

---

## 🔧 Fichiers Modifiés

| Fichier | Lignes ajoutées | Lignes modifiées | Type |
|---------|-----------------|-------------------|------|
| `config/market_selection.json` | +38 | 0 | Nouveau |
| `config/market_selection.py` | +98 | 0 | Nouveau |
| `ui/sidebar.py` | +103 | 3 | Modifié |
| `ui/builder_view.py` | +25 | 8 | Modifié |
| `agents/strategy_builder.py` | +58 | 12 | Modifié |
| **TOTAL** | **+322 lignes** | **23 lignes** | **5 fichiers** |

---

## 🚀 Prochaines Étapes (Optionnel — Architecture Propre)

Si vous voulez aller plus loin (Option E de l'audit) :

1. **Classe `MarketSelector`** : Encapsuler toute la logique de sélection
   - Méthodes : `select_from_ui()`, `select_from_llm()`, `apply_diversity()`
   - Avantage : Testabilité unitaire, séparation responsabilités

2. **Store partagé `recent_markets`** : Session state ou DB léger
   - Synchronisation entre UI et Builder
   - Évite drift entre les 2 historiques

3. **Event-driven** : Événements `market_selected`, `diversity_applied`
   - Découplage UI/Builder
   - Traçabilité temps-réel

4. **Tests d'intégration** : pytest avec mocks LLM
   - Tests unitaires pour `recommend_market_context`
   - Tests UI pour override LLM sur sélection manuelle

**Effort estimé :** ~2 jours (refactor complet)
**Gain :** Architecture solide, maintenance facilitée

---

## 📝 Notes Techniques

### Import Config

Les nouvelles fonctions importent `config.market_selection` localement (pas global) pour éviter circular imports :

```python
# Dans strategy_builder.py
from config.market_selection import get_diversity_min_alternatives

# Au lieu de:
# import config.market_selection  # ← Risque circular import si config importe strategy_builder
```

### Session State Marqueurs

Nouveaux marqueurs ajoutés :
- `st.session_state["_random_market_applied"]` : Détecte sélection 🎲 dans `get_final_market_selection()`
- Usage : Distinguer sélection manuelle vs aléatoire (même liste finale)

### Gestion Fallback

Si `llm_override` contient `source="fallback_no_candidates"`, la raison d'échec LLM est maintenant dans `reason` :
- Exemple : `"Univers marché incomplet, fallback par défaut."`
- Traçabilité améliorée pour debugging

---

## ⚠️ Points d'Attention

### 1. Config JSON Required

Le fichier `config/market_selection.json` DOIT exister au démarrage. Si absent :
```python
raise FileNotFoundError("Config marché manquante: config/market_selection.json")
```

**Action utilisateur :** Vérifier présence avant commit/deploy.

### 2. Breaking Change : Defaults Centralisés

Les defaults hardcodés dans `sidebar.py` (L470, L476) sont maintenant IGNORÉS si `market_selection.json` existe.

**Migration :** Tous les defaults doivent être dans JSON pour cohérence.

### 3. Log Level

Les nouveaux logs utilisent `logger.info()` et `logger.warning()`. Si `LOG_LEVEL=ERROR`, ils ne seront pas visibles.

**Recommandation :** `LOG_LEVEL=INFO` minimum en production pour traçabilité.

---

## ✅ Validation

**Checklist avant merge :**
- [ ] `config/market_selection.json` créé et validé (JSON valide)
- [ ] Tests manuels : Bouton 🎲, Bouton 🎯, auto_market_pick ON/OFF
- [ ] Logs visibles en console pour sélection UI et override LLM
- [ ] Warning UI affiché si override LLM détecté
- [ ] Aucune régression sur backtests existants (mode manuel)
- [ ] Documentation mise à jour (README si nécessaire)

---

## 📚 Références

- **Audit complet :** [AUDIT_MARKET_SELECTION.md](AUDIT_MARKET_SELECTION.md)
- **Issue fixée :** UnboundLocalError 'random' (sidebar.py L1427)
- **Config design :** JSON + overrides env vars (pattern industry standard)

---

**Auteur :** Claude Sonnet 4.5
**Date :** 2026-02-24
**Version :** 1.0 — Patch Minimal (Option A+)
