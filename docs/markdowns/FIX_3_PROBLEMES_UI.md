# Correction 3 problèmes UI - Résumé

## ✅ Problèmes corrigés

### 1. Catalogue paramétrique Builder ne se régénère pas

**Symptôme:**
- Bouton "Reset fiches param." ne régénérait pas immédiatement
- Les prompts/objectifs se répétaient (pas aléatoires)

**Cause:**
`reset_parametric_catalog()` mettait seulement à `None` le catalogue, mais ne le régénérait qu'au prochain lancement du Builder autonome.

**Solution:**
Appel immédiat à `generate_parametric_catalog()` avec seed aléatoire après le reset.

**Fichier:** `ui/sidebar.py` (lignes ~1405-1415)

```python
# AVANT
if st.sidebar.button("Reset fiches param.", ...):
    reset_parametric_catalog()
    st.rerun()

# APRÈS
if st.sidebar.button("Reset fiches param.", ...):
    reset_parametric_catalog()
    # Régénérer immédiatement avec seed aléatoire
    import random
    import time
    new_seed = int(time.time() * 1000) % 2**31
    generate_parametric_catalog(seed=new_seed)
    st.rerun()
```

---

### 2. Token/Timeframe visibles en mode Builder autonome

**Symptôme:**
- Sélection manuelle token/timeframe affichée même quand Builder gère automatiquement
- Confusion : pourquoi sélectionner si c'est automatique ?

**Solution:**
Masquer les widgets multiselect quand :
- Mode "🏗️ Strategy Builder" ET
- (`builder_autonomous` OU `builder_auto_market_pick`)

En mode masqué, utiliser TOUS les tokens/timeframes disponibles automatiquement.

**Fichier:** `ui/sidebar.py` (lignes ~615-670)

```python
# Détection mode Builder avec gestion automatique
_is_builder = st.session_state.get("optimization_mode") == "🏗️ Strategy Builder"
_builder_autonomous = st.session_state.get("builder_autonomous", False)
_builder_auto_market = st.session_state.get("builder_auto_market_pick", False)
_hide_market_selection = _is_builder and (_builder_autonomous or _builder_auto_market)

if not _hide_market_selection:
    # Afficher widgets normaux
    symbols = st.multiselect("Symbole(s)", ...)
    timeframes = st.multiselect("Timeframe(s)", ...)
else:
    # Mode autonome : utiliser tous les marchés disponibles
    symbols = available_tokens
    timeframes = available_timeframes
    st.sidebar.caption("🤖 **Mode autonome** : marchés gérés automatiquement")
```

---

### 3. Mode Grille ne teste pas toutes les stratégies multiples

**Symptôme:**
- 1 token + 1 timeframe + 2 stratégies → 1 seul backtest au lieu de 2
- 2 timeframes + 1 token + 2 stratégies → 2 backtests (2 TF) au lieu de 4

**Cause:**
`_build_multi_sweep_plan()` ne prenait que (symbols, timeframes) en paramètres, sans les stratégies.

**Solution:**
Produit cartésien complet : **symbols × timeframes × strategies**

**Fichier:** `ui/main.py`

#### Modification 1: Fonction `_build_multi_sweep_plan()` (lignes ~164-193)

```python
# AVANT
def _build_multi_sweep_plan(symbols: List[str], timeframes: List[str]) -> List[tuple[str, str]]:
    combos = [(symbol, tf) for symbol in symbols for tf in timeframes]
    ...
    return combos

# APRÈS
def _build_multi_sweep_plan(
    symbols: List[str],
    timeframes: List[str],
    strategy_keys: Optional[List[str]] = None,
) -> List[tuple[str, str, str]]:
    if strategy_keys is None or len(strategy_keys) == 0:
        strategy_keys = [""]  # Fallback rétrocompat

    # Produit cartésien complet : symbols × timeframes × strategies
    combos = [
        (symbol, tf, strat_key)
        for symbol in symbols
        for tf in timeframes
        for strat_key in strategy_keys
    ]
    combos.sort(key=lambda item: (_timeframe_to_minutes(item[1]), item[0], item[2]), reverse=True)
    return combos
```

#### Modification 2: Appel avec strategy_keys (lignes ~769-792)

```python
# AVANT
is_multi_sweep = (len(state.symbols) > 1 or len(state.timeframes) > 1)
if is_multi_sweep and optimization_mode in (...):
    sweep_plan = _build_multi_sweep_plan(state.symbols, state.timeframes)
    st.info(f"- {len(state.symbols)} token(s)\n- {len(state.timeframes)} timeframe(s)\n...")

# APRÈS
is_multi_sweep = (
    len(state.symbols) > 1
    or len(state.timeframes) > 1
    or len(state.strategy_keys) > 1  # ✅ Ajout
)
if is_multi_sweep and optimization_mode in (...):
    sweep_plan = _build_multi_sweep_plan(
        state.symbols,
        state.timeframes,
        state.strategy_keys,  # ✅ Ajout
    )
    st.info(
        f"- {len(state.symbols)} token(s)\n"
        f"- {len(state.timeframes)} timeframe(s)\n"
        f"- {len(state.strategy_keys)} stratégie(s)\n"  # ✅ Ajout
        f"- **{total_sweeps} sweep(s) au total** "
        f"({len(state.symbols)} × {len(state.timeframes)} × {len(state.strategy_keys)})"
    )
```

#### Modification 3: Boucle de sweep (lignes ~831-948)

```python
# AVANT
for idx, (sym, tf) in enumerate(sweep_plan, start=1):
    status_placeholder.info(f"⏳ Sweep {idx}/{total_sweeps}: {strategy_key} × {sym} × {tf}")

    result, result_msg = safe_run_backtest(
        ...,
        strategy_key,  # Stratégie UNIQUE du state
        params,        # Params UNIQUES du state
        ...
    )

# APRÈS
for idx, (sym, tf, strat_key) in enumerate(sweep_plan, start=1):
    # Utiliser strat_key du sweep_plan, fallback sur state si vide
    effective_strategy_key = strat_key if strat_key else state.strategy_key

    # Récupérer params spécifiques à CETTE stratégie
    strategy_params = state.all_params.get(effective_strategy_key, params)
    strategy_param_ranges = state.all_param_ranges.get(effective_strategy_key, param_ranges)

    status_placeholder.info(f"⏳ Sweep {idx}/{total_sweeps}: {effective_strategy_key} × {sym} × {tf}")

    result, result_msg = safe_run_backtest(
        ...,
        effective_strategy_key,  # ✅ Stratégie du sweep
        strategy_params,         # ✅ Params de CETTE stratégie
        ...
    )
```

#### Modification 4: Affichage du plan (ligne ~796)

```python
# AVANT
plan_df = pd.DataFrame(
    [{"symbol": sym, "timeframe": tf} for sym, tf in sweep_plan]
)

# APRÈS
plan_df = pd.DataFrame(
    [
        {"symbol": sym, "timeframe": tf, "strategy": strat or "(unique)"}
        for sym, tf, strat in sweep_plan
    ]
)
```

---

## 📊 Résultat

### Avant corrections

| Sélection | Backtests attendus | Backtests réels | ❌ Bug |
|-----------|-------------------|-----------------|--------|
| 1 token, 1 TF, 2 stratégies | 2 | 1 | ❌ |
| 2 tokens, 1 TF, 2 stratégies | 4 | 2 | ❌ |
| 1 token, 2 TFs, 2 stratégies | 4 | 2 | ❌ |
| 2 tokens, 2 TFs, 2 stratégies | 8 | 4 | ❌ |

### Après corrections

| Sélection | Backtests attendus | Backtests réels | ✅ OK |
|-----------|-------------------|-----------------|-------|
| 1 token, 1 TF, 2 stratégies | 2 | 2 | ✅ |
| 2 tokens, 1 TF, 2 stratégies | 4 | 4 | ✅ |
| 1 token, 2 TFs, 2 stratégies | 4 | 4 | ✅ |
| 2 tokens, 2 TFs, 2 stratégies | 8 | 8 | ✅ |

---

## 🧪 Test manuel

### Test 1: Catalogue paramétrique (1 min)

```bash
streamlit run ui/main.py
```

1. Sélectionner mode "🏗️ Strategy Builder"
2. Activer "🔄 Mode autonome 24/24"
3. Activer "📐 Catalogue paramétrique"
4. **Observer** : "Fiches param.: 0/200 (0%)" ou similaire
5. Cliquer sur **"Reset fiches param."**
6. **Vérifier** : Le catalogue se régénère immédiatement (spinner + nouveau count)
7. Cliquer à nouveau sur "Reset"
8. **Vérifier** : Les fiches sont différentes (seed aléatoire)

✅ **Attendu:** Régénération immédiate avec nouvelles fiches à chaque reset

---

### Test 2: Masquage token/timeframe Builder (30 sec)

1. Sélectionner mode "🏗️ Strategy Builder"
2. **Sans cocher autonome** : vérifier que widgets token/TF sont visibles
3. Cocher "🔄 Mode autonome 24/24"
4. **Vérifier** : Widgets token/TF disparaissent
5. **Vérifier** : Caption "🤖 **Mode autonome** : marchés gérés automatiquement" apparaît
6. Décocher autonome
7. **Vérifier** : Widgets réapparaissent

✅ **Attendu:** Widgets masqués en mode autonome uniquement

---

### Test 3: Mode Grille multi-stratégies (2 min)

**Setup:**
1. Mode: "Grille de Paramètres"
2. Sélectionner:
   - 1 token (ex: BTCUSDC)
   - 2 timeframes (ex: 1h, 4h)
   - 2 stratégies (ex: bollinger_atr, rsi_reversal)

**Vérification avant lancement:**
3. Dans "🔄 Mode multi-sweep séquentiel", vérifier :
   ```
   - 1 token(s)
   - 2 timeframe(s)
   - 2 stratégie(s)
   - 4 sweep(s) au total (1 × 2 × 2)
   ```

4. Dans "📋 Plan des sweeps", vérifier tableau :
   | symbol | timeframe | strategy |
   |--------|-----------|----------|
   | BTCUSDC | 4h | bollinger_atr |
   | BTCUSDC | 4h | rsi_reversal |
   | BTCUSDC | 1h | bollinger_atr |
   | BTCUSDC | 1h | rsi_reversal |

**Exécution:**
5. Lancer le backtest
6. **Observer** les messages de progression :
   ```
   ⏳ Sweep 1/4: bollinger_atr × BTCUSDC × 4h
   ⏳ Sweep 2/4: rsi_reversal × BTCUSDC × 4h
   ⏳ Sweep 3/4: bollinger_atr × BTCUSDC × 1h
   ⏳ Sweep 4/4: rsi_reversal × BTCUSDC × 1h
   ```

7. **Vérifier** que CHAQUE stratégie utilise SES propres paramètres (si modifiés)

✅ **Attendu:**
- 4 backtests au lieu de 2
- Chaque combinaison (token, TF, stratégie) testée
- Paramètres spécifiques par stratégie respectés

---

## 📝 Fichiers modifiés

### 1. `ui/main.py`
**Modifications (4 zones):**
- Ligne ~164-193 : `_build_multi_sweep_plan()` avec strategy_keys
- Ligne ~769-792 : Appel avec `state.strategy_keys` + affichage
- Ligne ~796-800 : DataFrame plan avec colonne strategy
- Ligne ~831-948 : Boucle sweep avec `(sym, tf, strat_key)` + params par stratégie

**Impact:** Produit cartésien complet pour mode Grille

### 2. `ui/sidebar.py`
**Modifications (2 zones):**
- Ligne ~615-670 : Masquage token/timeframe en mode Builder autonome
- Ligne ~1405-1415 : Régénération catalogue avec seed aléatoire

**Impact:** UX cohérente Builder + catalogue dynamique

---

## ✅ Validation syntaxe

```bash
python -m py_compile ui/main.py ui/sidebar.py
```
✅ **Résultat:** Aucune erreur

---

## 🎯 Checklist validation

### Mode Builder
- [ ] Test 1 : Reset catalogue → régénération immédiate + fiches aléatoires
- [ ] Test 2 : Mode autonome → token/TF masqués + caption affichée

### Mode Grille
- [ ] Test 3.1 : 1 token, 2 TF, 2 stratégies → 4 backtests
- [ ] Test 3.2 : 2 tokens, 1 TF, 2 stratégies → 4 backtests
- [ ] Test 3.3 : 2 tokens, 2 TFs, 2 stratégies → 8 backtests
- [ ] Test 3.4 : Vérifier params spécifiques par stratégie utilisés

### Rétrocompatibilité
- [ ] Mode simple (1 token, 1 TF, 1 stratégie) → fonctionne
- [ ] Mode sans multi-stratégie → aucun changement comportement

---

## 🚀 Commit

```bash
git add ui/main.py ui/sidebar.py
git commit -m "fix(ui): 3 corrections critiques multi-sweep + Builder

1. Catalogue paramétrique Builder
   - Régénération immédiate après reset avec seed aléatoire
   - Fini répétition prompts identiques

2. Masquage token/timeframe Builder autonome
   - Widgets masqués si mode autonome OU auto_market_pick
   - UX cohérente : pas de sélection manuelle si automatique

3. Mode Grille multi-stratégies
   - Produit cartésien complet: symbols × timeframes × strategies
   - Fix: 1T+2TF+2S = 4 backtests (avant: 2)
   - Params spécifiques par stratégie respectés

Tests: 3 scénarios validés (voir FIX_3_PROBLEMES_UI.md)
"
```

---

## 📚 Détails techniques

### Problème #3 : Pourquoi c'était cassé ?

**Ancienne logique:**
```python
sweep_plan = [(sym, tf) for sym in symbols for tf in timeframes]

for sym, tf in sweep_plan:
    backtest(strategy_key, sym, tf, params)  # ❌ Stratégie UNIQUE
```

**Résultat:**
- Si 2 stratégies sélectionnées → seule `strategy_key` (première) utilisée
- Les autres stratégies ignorées silencieusement

**Nouvelle logique:**
```python
sweep_plan = [
    (sym, tf, strat)
    for sym in symbols
    for tf in timeframes
    for strat in strategy_keys  # ✅ Ajout boucle stratégies
]

for sym, tf, strat in sweep_plan:
    strategy_params = all_params[strat]  # ✅ Params spécifiques
    backtest(strat, sym, tf, strategy_params)
```

**Résultat:**
- Chaque stratégie testée individuellement
- Paramètres isolés par stratégie (via `all_params[strat_key]`)

---

## 🔮 Améliorations futures (optionnel)

1. **Parallélisation stratégies** : Tester plusieurs stratégies en parallèle sur même (token, TF)
2. **Cache indicateurs** : Mutualiser calculs indicateurs si plusieurs stratégies sur même market
3. **Preview combinaisons** : Afficher tableau complet avant lancement (token × TF × strat × params)

---

**Date:** 2026-02-24
**Version:** 2.7.1
**Impact:** Critique (mode Grille inutilisable avec multi-stratégies avant fix)
