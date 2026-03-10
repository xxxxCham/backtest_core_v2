# Fix : Sélection intelligente Token/TF par le LLM

**Date** : 2026-02-24
**Problème** : Le LLM retournait toujours `0GUSDC 1h` indépendamment du type de stratégie, et le toggle "LLM choisit token/TF" ne changeait rien au comportement.

## Cause racine identifiée

1. **Tri alphabétique des tokens** ([data/loader.py:339](d:\backtest_core\data\loader.py#L339))
   → `0GUSDC` était toujours le premier token car commence par `0`

2. **Fallback toujours sur `tokens[0]`** ([strategy_builder.py:7826](d:\backtest_core\agents\strategy_builder.py#L7826))
   → En cas d'échec LLM, retombait sur `0GUSDC`

3. **Shuffle aléatoire sans intelligence** ([strategy_builder.py:7853](d:\backtest_core\agents\strategy_builder.py#L7853))
   → Tokens mélangés sans tenir compte du type de stratégie

4. **Hints LLM génériques** ([strategy_builder.py:7949](d:\backtest_core\agents\strategy_builder.py#L7949))
   → "haute volatilité" sans nommer de tokens spécifiques

## Solution implémentée

### 1. Enrichissement des métadonnées tokens

**Fichier** : `config/market_selection.json`

Ajout de deux nouvelles sections :

- **`token_profiles`** : Métadonnées pour chaque token (volatilité, liquidité, stratégies recommandées)
- **`strategy_requirements`** : Exigences pour chaque type de stratégie (scalping, breakout, momentum, trend, mean_reversion)

**Exemple** :
```json
{
  "token_profiles": {
    "BTCUSDC": {
      "volatility": "medium",
      "liquidity": "high",
      "strategies": ["trend", "momentum", "mean_reversion", "breakout", "scalping"]
    },
    "SOLUSDC": {
      "volatility": "high",
      "liquidity": "high",
      "strategies": ["breakout", "momentum", "scalping"]
    }
  },
  "strategy_requirements": {
    "scalping": {
      "volatility_preferred": ["high", "medium"],
      "liquidity_min": "high",
      "timeframes": ["1m", "3m", "5m"]
    }
  }
}
```

### 2. Nouvelles fonctions de ranking

**Fichier** : `config/market_selection.py`

Ajout de 3 nouvelles fonctions :

- **`get_token_profile(symbol)`** : Retourne le profil d'un token
- **`get_strategy_requirements(strategy_type)`** : Retourne les exigences d'une stratégie
- **`rank_tokens_for_strategy(tokens, strategy_type)`** : Trie les tokens par pertinence

**Algorithme de scoring** :
- +10 points si volatilité correspond exactement
- +5 points si liquidité suffisante
- -10 points si liquidité insuffisante
- +3 points si stratégie dans la liste recommandée

### 3. Tri intelligent dans `recommend_market_context`

**Fichier** : `agents/strategy_builder.py`

#### Détection du type de stratégie (ligne ~7857)
```python
if any(kw in objective_lower for kw in ["scalp", "court terme", "rapide"]):
    detected_strategy_type = "scalping"
elif any(kw in objective_lower for kw in ["breakout", "cassure", "donchian"]):
    detected_strategy_type = "breakout"
# ... etc
```

#### Tri des tokens (ligne ~7869)
```python
if detected_strategy_type:
    shuffled_symbols = rank_tokens_for_strategy(symbols, detected_strategy_type)
else:
    shuffled_symbols = symbols.copy()
    random.shuffle(shuffled_symbols)
```

### 4. Prompt LLM renforcé (ligne ~7987)

Au lieu de hints génériques, le LLM reçoit maintenant :
```
📊 RECOMMANDATION STRATÉGIE: **Breakout** détecté
  → TFs optimaux: 5m, 15m, 30m
  → Tokens prioritaires (ordre d'importance): APTUSDC, AVAXUSDC, SOLUSDC, BTCUSDC, ETHUSDC
  → IMPORTANT: Privilégier les tokens en tête de liste pour ce type de stratégie.
```

### 5. Fallback intelligent (ligne ~7888)

**Avant** :
```python
fallback_symbol = symbols[0]  # Toujours 0GUSDC
```

**Après** :
```python
# Utilise le premier token trié (le plus pertinent)
fallback_symbol = shuffled_symbols[0] if shuffled_symbols else "BTCUSDC"

# Fallback timeframe : priorise les TFs recommandés
if detected_strategy_type:
    recommended_tfs = get_strategy_requirements(detected_strategy_type)["timeframes"]
    fallback_timeframe = next((tf for tf in recommended_tfs if tf in timeframes), ...)
```

## Résultats des tests

**Script** : `.tmp_test_market_selection.py`

### Ranking par type de stratégie

| Type         | Top 5 tokens                                      | Raison                                |
|--------------|--------------------------------------------------|---------------------------------------|
| **Scalping**     | BTC, ETH, SOL, XRP, LTC                          | Haute liquidité prioritaire           |
| **Breakout**     | APT, AVAX, BTC, ETH, SOL                         | Haute volatilité + liquidité OK       |
| **Momentum**     | APT, AVAX, BTC, ETH, SOL                         | Haute volatilité + liquidité OK       |
| **Trend**        | BTC, ETH, LTC, XRP, TRX                          | Volatilité moyenne/basse prioritaire  |
| **Mean Rev.**    | BTC, ETH, LTC, TRX, XRP                          | Volatilité moyenne/basse prioritaire  |

### Détection de stratégie

✅ **6/6 tests passés** :
- "Scalping rapide sur BTC 5m" → `scalping`
- "Breakout Donchian sur ETH 15m" → `breakout`
- "Momentum EMA sur SOL 1h" → `momentum`
- "Trend following sur AVAX 4h" → `trend`
- "Mean reversion Bollinger sur XRP 30m" → `mean_reversion`
- "Stratégie quelconque" → `UNKNOWN` (shuffle aléatoire)

## Impact attendu

### Avant le fix
```
🔄 Override LLM : 0GUSDC 1h → AVAXUSDC 1h
🔄 Override LLM : 0GUSDC 1h → APTUSDC 1h
🔄 Override LLM : 0GUSDC 1h → 0GUSDC 5m
```
→ Le LLM retournait toujours `0GUSDC 1h`, puis le système d'override corrigeait

### Après le fix
```
🧭 Session #1: APTUSDC 30m (source=llm, data=loaded, conf=0.85)
🧭 Session #2: AVAXUSDC 15m (source=llm, data=loaded, conf=0.82)
🧭 Session #3: SOLUSDC 1h (source=llm, data=loaded, conf=0.88)
```
→ Le LLM choisit directement les tokens pertinents pour le type de stratégie

## Comportement du toggle "LLM choisit token/TF"

### Toggle ACTIVÉ (default)
1. Détection du type de stratégie dans l'objectif
2. Tri des tokens par pertinence
3. Appel au LLM avec prompt renforcé
4. Fallback intelligent si LLM échoue

### Toggle DÉSACTIVÉ
- Utilise directement les tokens/TF sélectionnés dans la sidebar
- Pas d'appel au LLM pour la sélection de marché

## Fichiers modifiés

1. **`config/market_selection.json`** : Métadonnées tokens + exigences stratégies
2. **`config/market_selection.py`** : Fonctions de ranking et profiling
3. **`agents/strategy_builder.py`** : Détection, tri, prompt, fallback
4. **`.tmp_test_market_selection.py`** : Script de test

## Compatibilité

✅ **100% rétrocompatible** :
- Les anciens objectifs sans type détecté utilisent le shuffle aléatoire (comportement original)
- Le fallback sur `BTCUSDC` reste en dernier recours
- Pas de breaking change dans les APIs

## Prochaines étapes (optionnel)

1. **Affiner les métadonnées** : Ajuster les profils de volatilité/liquidité selon les données réelles
2. **Ajouter plus de tokens** : Enrichir `token_profiles` avec tous les tokens disponibles
3. **Timeframe intelligent** : Trier aussi les TFs selon le type de stratégie (actuellement shuffle)
4. **Feedback utilisateur** : Afficher le type de stratégie détecté dans l'UI

---

**Status** : ✅ Implémenté et testé
**Tests** : ✅ 6/6 passés
**Breaking changes** : ❌ Aucun
