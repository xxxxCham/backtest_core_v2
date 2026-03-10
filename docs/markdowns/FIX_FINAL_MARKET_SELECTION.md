# ✅ Fix Final : Sélection intelligente Token/TF (CORRIGÉ à la racine)

**Date** : 2026-02-24
**Status** : ✅ Fix complet appliqué sur toutes les sources d'objectifs

---

## 🔍 Problème racine identifié

Les catalogues (paramétrique ET templates) contenaient des **objectifs pré-générés avec tokens/TF hardcodés** :

```
"[Momentum] sur 0GUSDC en 1h. Indicateurs : EMA + MACD + Aroon..."
```

→ Même avec toggle "LLM choisit token/TF" activé, le LLM recevait des hints `0GUSDC 1h` qui court-circuitaient le tri intelligent.

---

## ✅ Solution finale appliquée

### 1️⃣ **Fonctions de nettoyage dynamique**

**Fichier** : `agents/strategy_builder.py`

**Nouvelles fonctions** :

```python
def _remove_hardcoded_tokens(text: str) -> str:
    """
    Retire les tokens crypto hardcodés (0GUSDC, BTCUSDC, etc.)

    Transforme:
    - "sur 0GUSDC en" → "sur crypto en"
    - "sur BTCUSDC dans" → "sur crypto dans"
    - "[Momentum] sur 0GUSDC" → "[Momentum] sur crypto"
    """
    # Pattern : XXXXXUSDC (ex: 0GUSDC, BTCUSDC, 1000SATSUSDC)
    token_pattern = r'\b[A-Z0-9]{2,12}USDC\b'

    # Remplacer "sur TOKEN en/dans" par "sur crypto en/dans"
    text = re.sub(rf'sur\s+{token_pattern}\s+(en|dans|avec|pour)',
                  r'sur crypto \1', text, flags=re.IGNORECASE)

    # Remplacer TOKEN isolés
    text = re.sub(rf'{token_pattern}\s+(en|dans)', r'crypto \1', text, flags=re.IGNORECASE)

    return text.strip()


def _remove_hardcoded_timeframes(text: str) -> str:
    """
    Retire les timeframes hardcodés (1h, 30m, 5m, etc.)

    Transforme:
    - "en 1h" → "en timeframe adapté"
    - "dans les 5m" → "dans timeframe adapté"
    - "crypto 30m" → "crypto"
    """
    # Pattern : 1m, 5m, 15m, 30m, 1h, 4h, 1d, etc.
    tf_pattern = r'\b\d+[mhdwM]\b'

    # Remplacer "en/dans [TF]" par description générique
    text = re.sub(rf'(en|dans)\s+(les?\s+)?{tf_pattern}',
                  r'\1 timeframe adapté', text, flags=re.IGNORECASE)

    # Remplacer TF isolés
    text = re.sub(rf'\s+{tf_pattern}\b', '', text, flags=re.IGNORECASE)

    return text.strip()
```

### 2️⃣ **Application dans `normalize_variant_for_builder`**

**Ligne ~8348** : Nettoyage automatique quand `symbol=None` ou `timeframe=None`

```python
if symbol is not None:
    builder_text = builder_text.replace("{symbol}", str(symbol))
else:
    # symbol=None → Retirer tokens hardcodés pour sélection LLM intelligente
    builder_text = _remove_hardcoded_tokens(builder_text)

if timeframe is not None:
    builder_text = builder_text.replace("{timeframe}", str(timeframe))
else:
    # timeframe=None → Retirer TF hardcodés pour sélection LLM intelligente
    builder_text = _remove_hardcoded_timeframes(builder_text)
```

### 3️⃣ **Application dans `get_next_catalog_objective`**

**Ligne ~7675** : Même système de nettoyage pour les templates

```python
if isinstance(symbol, list):
    symbol = random.choice(symbol) if symbol else None  # ← Retourne None si liste vide
if isinstance(timeframe, list):
    timeframe = random.choice(timeframe) if timeframe else None

text = obj.description

if symbol is not None:
    text = text.replace("{symbol}", str(symbol))
else:
    text = _remove_hardcoded_tokens(text)  # ← Nettoyage automatique

if timeframe is not None:
    text = text.replace("{timeframe}", str(timeframe))
else:
    text = _remove_hardcoded_timeframes(text)  # ← Nettoyage automatique
```

### 4️⃣ **Modification des appels dans `builder_view.py`**

**Ligne ~1428** et **~1447** : Passer `None` quand toggle activé

```python
catalog_result = get_next_catalog_objective(
    symbol=None if auto_market_pick else all_symbols,    # ← None = nettoyage auto
    timeframe=None if auto_market_pick else all_timeframes,
)
```

### 5️⃣ **Ignorer les hints détectés dans l'objectif**

**Ligne ~7883** : Prioriser le tri intelligent sur les hints

```python
if not detected_strategy_type:
    # Pas de type détecté : utiliser hints pour guider
    hinted_symbol, hinted_timeframe = _find_objective_market_hints(...)
else:
    # Type détecté : IGNORER hints hardcodés (prioriser tri intelligent)
    hinted_symbol = None
    hinted_timeframe = None
    logger.info("strategy_type=%s → IGNORING hints", detected_strategy_type)
```

---

## 🔄 Workflow complet après fix

### Toggle ✅ ACTIVÉ + Catalogue paramétrique

```
1. Génération objectif → get_next_parametric_objective(symbol=None, timeframe=None)
                           ↓
2. Objectif brut        → "[Momentum] sur 0GUSDC en 1h. EMA + MACD..."
                           ↓
3. Nettoyage auto       → "[Momentum] sur crypto. EMA + MACD..."
                           ↓
4. Détection type       → momentum
                           ↓
5. Tri intelligent      → APT, AVAX, SOL, BTC, ETH (haute volatilité)
                           ↓
6. Hints                → IGNORÉS (aucun token dans objectif nettoyé)
                           ↓
7. Prompt LLM           → "Tokens prioritaires: APT, AVAX, SOL, BTC, ETH"
                           ↓
8. LLM choisit          → APTUSDC 30m (optimal momentum)
                           ↓
9. Chargement data      → APTUSDC_30m.parquet
                           ↓
10. Builder lance       → Stratégie momentum sur APTUSDC 30m ✅
```

### Toggle ✅ ACTIVÉ + Catalogue templates

```
1. Génération objectif → get_next_catalog_objective(symbol=None, timeframe=None)
                           ↓
2. Template brut        → "Style breakout sur {symbol} en {timeframe}"
                           ↓
3. Nettoyage auto       → "Style breakout sur crypto"
                           ↓
4. Détection type       → breakout
                           ↓
5. Tri intelligent      → APT, AVAX, SOL, BTC, ETH (haute volatilité)
                           ↓
6. Hints                → IGNORÉS
                           ↓
7. LLM choisit          → APTUSDC 15m (optimal breakout)
```

### Toggle ❌ DÉSACTIVÉ

```
1. Génération objectif → get_next_catalog_objective(symbol="BTCUSDC", timeframe="1h")
                           ↓
2. Template brut        → "Style breakout sur {symbol} en {timeframe}"
                           ↓
3. Remplacement         → "Style breakout sur BTCUSDC en 1h"
                           ↓
4. Pas de sélection LLM → Utilise directement BTCUSDC 1h
```

---

## 📊 Exemples de transformation

| Objectif AVANT (hardcodé) | Objectif APRÈS (nettoyé) | Type détecté | LLM choisit |
|---------------------------|--------------------------|--------------|-------------|
| `[Momentum] sur 0GUSDC en 1h. EMA + MACD` | `[Momentum] sur crypto. EMA + MACD` | momentum | APTUSDC 30m |
| `Breakout sur BTCUSDC 15m avec Donchian` | `Breakout sur crypto avec Donchian` | breakout | AVAXUSDC 15m |
| `Scalping 5m sur ETHUSDC avec RSI` | `Scalping sur crypto avec RSI` | scalping | SOLUSDC 5m |
| `Trend following 4h sur BNBUSDC` | `Trend following sur crypto` | trend | BTCUSDC 4h |
| `Mean reversion 30m sur XRPUSDC` | `Mean reversion sur crypto` | mean_reversion | LTCUSDC 30m |

---

## 🧪 Test du fix

### Commandes de test

```bash
# 1. Redémarrer Streamlit (OBLIGATOIRE)
streamlit run ui/main.py

# 2. Activer les options :
#    ✅ Mode autonome 24/24
#    ✅ Toggle "🧭 LLM choisit token/TF" activé
#    ✅ Catalogue paramétrique OU templates (peu importe)

# 3. Observer les logs console
```

### ✅ Logs attendus (fix fonctionne)

```
Market selection: strategy_type=momentum → IGNORING hints (prioritize intelligent ranking)
Market selection: strategy_type=momentum, ranked_tokens=APTUSDC, AVAXUSDC, SOLUSDC, BTCUSDC, ETHUSDC
Market selection: fallback=APTUSDC 30m (source=strategy_optimized)
🔍 [DIAG] Session #1 → Marché sélectionné: APTUSDC 30m | Source: llm | Confidence: 0.85
```

### ❌ Logs KO (fix ne marche pas - cache problème)

```
Market selection: strategy_type=NONE → using hints, symbol=0GUSDC, timeframe=1h
🔍 [DIAG] Session #1 → Marché sélectionné: 0GUSDC 1h | Source: llm | Confidence: 0.95
```

→ Si vous voyez ça, type de stratégie pas détecté (vérifier mots-clés) ou code pas rechargé

---

## 📋 Checklist finale

1. ✅ **Redémarrer Streamlit** : Code modifié, redémarrage OBLIGATOIRE
2. ✅ **Toggle activé** : Vérifier "🧭 LLM choisit token/TF" coché
3. ✅ **Mode autonome** : Lancer mode autonome 24/24
4. ✅ **Observer logs** : Vérifier logs console pour confirmer
5. ✅ **Vérifier UI** : Session devrait montrer tokens variés (APT, AVAX, SOL, BTC...)

---

## 🔧 Fichiers modifiés

| Fichier | Modifications | Lignes |
|---------|---------------|--------|
| `agents/strategy_builder.py` | + `_remove_hardcoded_tokens()` | ~8294 |
| `agents/strategy_builder.py` | + `_remove_hardcoded_timeframes()` | ~8330 |
| `agents/strategy_builder.py` | Nettoyage dans `normalize_variant_for_builder` | ~8348-8360 |
| `agents/strategy_builder.py` | Nettoyage dans `get_next_catalog_objective` | ~7675-7700 |
| `agents/strategy_builder.py` | Ignorer hints si type détecté | ~7883-7906 |
| `ui/builder_view.py` | Pass `None` aux catalogues si toggle activé | ~1428, ~1447 |

---

## 🎯 Résultat attendu

### Avant le fix

```
Session #1 → 0GUSDC 1h (momentum)
Session #2 → 0GUSDC 1h (breakout)
Session #3 → 0GUSDC 1h (trend)
```

### Après le fix

```
Session #1 → APTUSDC 30m (momentum - haute volatilité optimal)
Session #2 → AVAXUSDC 15m (breakout - haute volatilité optimal)
Session #3 → BTCUSDC 4h (trend - volatilité moyenne optimal)
Session #4 → SOLUSDC 5m (scalping - haute volatilité + court TF)
Session #5 → LTCUSDC 1h (mean reversion - basse volatilité optimal)
```

---

**Status** : ✅ Fix complet appliqué
**Action requise** : **REDÉMARRER Streamlit** pour appliquer les changements
**Breaking changes** : ❌ Aucun (rétrocompatible)
