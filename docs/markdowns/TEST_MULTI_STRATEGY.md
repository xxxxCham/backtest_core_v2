# Test Manuel Multi-Strategy Parameters

## Prérequis

```bash
# Vérifier que l'environnement est activé
cd d:\backtest_core
# Si nécessaire: conda activate backtest_env (ou votre env)
```

---

## Test 1: Affichage des paramètres (2 min)

### Étapes

```bash
# 1. Lancer l'UI
streamlit run ui/main.py
```

**Dans l'interface:**

1. Dans la sidebar, **sélectionner 1 stratégie** (ex: `bollinger_atr`)
   - ✅ **Attendu:** Les paramètres s'affichent normalement (comportement actuel)

2. **Sélectionner 2 stratégies** dans le multiselect (ex: `bollinger_atr` + `rsi_reversal`)
   - ✅ **Attendu:** Deux sections distinctes apparaissent :
     ```
     📋 Stratégie 1: bollinger_atr
       [sliders: bb_period, bb_std, entry_level, ...]

     📋 Stratégie 2: rsi_reversal
       [sliders: rsi_period, rsi_oversold, rsi_overbought, ...]
     ```

3. **Vérifier que TOUS les paramètres sont visibles**
   - Chaque slider doit afficher sa valeur par défaut
   - Ex: `bb_period` devrait être à 20 (ou selon votre config)

### ✅ Critère de succès
- 2 sections bien séparées
- Tous les paramètres de chaque stratégie affichés
- Pas de widgets avec clés en conflit (pas d'erreur Streamlit)

---

## Test 2: Modification et persistance (3 min)

### Étapes

**Dans l'UI (avec 2 stratégies sélectionnées):**

1. **Modifier un paramètre de Stratégie 1**
   - Ex: Mettre `bb_period` à **25** au lieu de 20
   - ✅ **Attendu:** Le slider se met à jour immédiatement

2. **Modifier un paramètre de Stratégie 2**
   - Ex: Mettre `rsi_period` à **18** au lieu de 14
   - ✅ **Attendu:** Le slider se met à jour immédiatement

3. **Vérifier l'isolation**
   - Les modifications de Stratégie 1 ne doivent PAS affecter Stratégie 2
   - Les modifications de Stratégie 2 ne doivent PAS affecter Stratégie 1

4. **Recharger la page** (F5 ou Ctrl+R)
   - ✅ **Attendu:** Les valeurs modifiées sont **conservées**
     - `bb_period` reste à 25
     - `rsi_period` reste à 18

### ✅ Critère de succès
- Modifications indépendantes entre stratégies
- Valeurs persistées après rerun/reload

---

## Test 3: Exécution backtest (5 min)

### Étapes

**Préparation:**

1. Sélectionner **2 stratégies** (ex: bollinger_atr + rsi_reversal)
2. **Laisser les defaults** pour Stratégie 1
3. **Modifier un paramètre** de Stratégie 2 (ex: `rsi_period` à 18)

**Exécution:**

4. Sélectionner un token (ex: BTCUSDC) et timeframe (ex: 1h)
5. Mode: **Backtest Simple**
6. Cliquer sur **"Lancer le backtest"**

**Vérification:**

7. Dans les résultats, chercher les informations de config
   - Si debug activé, vérifier dans la console/logs :
     ```
     [DEBUG] Stratégie: bollinger_atr, params: {'bb_period': 20, ...}
     [DEBUG] Stratégie: rsi_reversal, params: {'rsi_period': 18, ...}
     ```

8. **Relancer avec `rsi_period` à 14 (default)**
   - ✅ **Attendu:** Les résultats de `rsi_reversal` doivent être **différents**
     (Sharpe, trades, PnL, etc.)

### Activation debug (optionnel)

Pour voir les params transmis au backtest, ajouter temporairement dans `ui/main.py` :

```python
# Dans la fonction qui lance le backtest (ex: render_main())
# Après construction de sidebar_state

print("\n[DEBUG MULTI-STRATEGY PARAMS]")
for strat_key, params in sidebar_state.all_params.items():
    print(f"  {strat_key}: {params}")
print()
```

### ✅ Critère de succès
- Les 2 stratégies s'exécutent sans erreur
- Les résultats de la stratégie avec params modifiés sont différents des defaults
- Les logs (si activés) montrent les params corrects

---

## Test 4: Mode Grille (3 min)

### Étapes

1. **Passer en mode** "Grille de Paramètres" (dans le selectbox du mode d'optimisation)
2. **Sélectionner 2 stratégies** (ex: bollinger_atr + rsi_reversal)
3. ✅ **Attendu:** Chaque stratégie affiche des **expanders** pour définir les ranges
   ```
   📋 Stratégie 1: bollinger_atr
     📊 bb_period
       [min: 10, max: 30, step: 2]
     📊 bb_std
       [min: 1.5, max: 3.0, step: 0.5]
     ...

   📋 Stratégie 2: rsi_reversal
     📊 rsi_period
       [min: 10, max: 20, step: 2]
     ...
   ```

4. **Définir un range pour un paramètre de chaque stratégie**
   - Ex: `bb_period` → min=15, max=25, step=5 (3 valeurs)
   - Ex: `rsi_period` → min=10, max=18, step=4 (3 valeurs)

5. **Vérifier la section "📌 Combinaisons multi-stratégies"**
   - ✅ **Attendu:** Affiche le nombre de combinaisons par stratégie
     ```
     • bollinger_atr: 27 combinaisons (3 × 3 × 3)
     • rsi_reversal: 81 combinaisons (3 × 3 × 3 × 3)
     Total sweep: 2 stratégies × N combos
     ```

### ✅ Critère de succès
- Chaque stratégie affiche ses ranges configurables
- Le calcul du nombre de combinaisons est cohérent
- Pas d'erreur "plage invalide"

---

## Test 5: Ajout/Retrait de stratégies (2 min)

### Étapes

1. **Sélectionner 3 stratégies** A, B, C (ex: bollinger_atr, rsi_reversal, ema_cross)
2. **Modifier des paramètres** de chaque stratégie :
   - A: `bb_period` → 25
   - B: `rsi_period` → 18
   - C: `ema_fast` → 10

3. **Retirer la stratégie B** de la sélection
   - ✅ **Attendu:**
     - A et C restent affichées avec leurs valeurs (25 et 10)
     - B disparaît de l'UI

4. **Re-sélectionner B**
   - ✅ **Attendu:** Les paramètres de B sont **restaurés** (`rsi_period` = 18)

### ✅ Critère de succès
- L'état des stratégies non retirées est préservé
- L'état des stratégies retirées est conservé en mémoire (restauration possible)

---

## Test 6: Edge cases (2 min)

### Test 6.1: Stratégie unique

1. **Sélectionner UNE SEULE stratégie**
2. ✅ **Attendu:** Comportement identique à avant le fix (widgets normaux, pas de section "📋 Stratégie 1")

### Test 6.2: Même stratégie 2 fois (rare)

Si le multiselect permet de sélectionner la même stratégie plusieurs fois :

1. **Sélectionner `bollinger_atr` deux fois** (si possible)
2. ✅ **Attendu:** Deux sections distinctes avec clés uniques
   ```
   📋 Stratégie 1: bollinger_atr
   📋 Stratégie 2: bollinger_atr
   ```

### Test 6.3: Stratégie sans paramètres

Si une stratégie n'a pas de `parameter_specs` :

1. **Sélectionner cette stratégie + une autre**
2. ✅ **Attendu:** Seule la stratégie avec params affiche des widgets (l'autre est ignorée silencieusement)

---

## Debugging (si erreur)

### Vérifier l'état Streamlit

Dans l'UI, ouvrir la console Python (Settings → Debug → Show Streamlit State) ou ajouter :

```python
import streamlit as st
st.write(st.session_state.get("multi_strategy_params", {}))
```

**Résultat attendu:**
```python
{
    "bollinger_atr": {"bb_period": 25, "bb_std": 2.0, ...},
    "rsi_reversal": {"rsi_period": 18, "rsi_oversold": 30, ...}
}
```

### Logs de propagation

Ajouter dans `backtest/worker.py` ou `backtest/engine.py` :

```python
print(f"[WORKER] Backtest de {strategy_key} avec params: {params}")
```

### Erreurs courantes

| Erreur | Cause probable | Solution |
|--------|----------------|----------|
| `DuplicateWidgetID` | Clés de widgets non uniques | Vérifier que `unique_key_prefix` contient bien `idx` |
| Valeurs non persistées | `st.session_state` non initialisé | Vérifier que `render_multi_strategy_params` est appelé |
| Paramètres = defaults au lieu des modifiés | Pipeline ne lit pas `all_params` | Vérifier que `sidebar_state.all_params[strat_key]` est utilisé dans le backtest |

---

## Checklist complète

### Pré-lancement
- [ ] Environnement activé
- [ ] UI lance sans erreur : `streamlit run ui/main.py`

### Tests fonctionnels
- [ ] Test 1: Affichage 2+ stratégies → sections distinctes
- [ ] Test 2: Modification → persistance après rerun
- [ ] Test 3: Backtest → params modifiés utilisés (≠ defaults)
- [ ] Test 4: Mode Grille → ranges configurables par stratégie
- [ ] Test 5: Ajout/retrait → état préservé et restauré

### Edge cases
- [ ] Test 6.1: 1 stratégie → comportement actuel
- [ ] Test 6.2: Même stratégie 2× → sections uniques
- [ ] Test 6.3: Stratégie sans params → ignorée silencieusement

### ✅ Validation finale
- [ ] Aucune erreur dans console Streamlit
- [ ] Aucune erreur dans logs backtest
- [ ] Résultats cohérents (params modifiés → résultats différents)

---

## Résultat attendu (récap)

### Avant le fix
```
[UI] Stratégie 1: bollinger_atr [params configurables]
[UI] Stratégie 2: rsi_reversal [PAS de widgets → defaults silencieux]

[Backtest] bollinger_atr avec bb_period=25 ✅
[Backtest] rsi_reversal avec rsi_period=14 ❌ (default forcé)
```

### Après le fix
```
[UI] Stratégie 1: bollinger_atr [params configurables]
[UI] Stratégie 2: rsi_reversal [params configurables] ✅

[Backtest] bollinger_atr avec bb_period=25 ✅
[Backtest] rsi_reversal avec rsi_period=18 ✅
```

---

## Contact / Support

En cas de bug non couvert par ce guide :

1. Vérifier `FIX_MULTI_STRATEGY_PARAMS.md` (doc complète)
2. Activer debug : `st.write(st.session_state["multi_strategy_params"])`
3. Comparer `all_params` UI vs params reçus par le backtest
4. Ouvrir une issue avec les logs d'erreur
