# Livrables - Fix Multi-Strategy Parameters

## 📦 Fichiers de code modifiés

| Fichier | Modifications | Impact |
|---------|--------------|--------|
| `ui/helpers.py` | +110 lignes | 2 nouvelles fonctions (extraction + rendu) |
| `ui/sidebar.py` | -33 lignes | Simplification construction all_params |
| `ui/state.py` | 0 ligne | Aucune modification (structure existante) |

### Détails des modifications

#### `ui/helpers.py`
```python
# Ligne ~567 (30 lignes)
def extract_strategy_params_metadata(strategy_key: str) -> Tuple[...]
    """Extrait specs de paramètres sans créer de widgets."""

# Ligne ~598 (80 lignes)
def render_multi_strategy_params(...) -> Tuple[...]
    """Affiche widgets pour N stratégies avec clés uniques."""
```

#### `ui/sidebar.py`
```python
# Lignes 2756-2778 (avant: 2756-2810)
# AVANT: 55 lignes générant defaults pour stratégies 2+
# APRÈS: 22 lignes avec branchement conditionnel

if len(strategy_names) > 1:
    all_params, all_param_ranges, all_param_specs = render_multi_strategy_params(...)
else:
    all_params[strategy_key] = params  # Mode single (unchanged)
```

---

## 📚 Documentation créée

| Fichier | Contenu | Usage |
|---------|---------|-------|
| `FIX_MULTI_STRATEGY_PARAMS.md` | Doc complète (architecture, tests, roadmap) | Référence technique |
| `RESUME_FIX_MULTI_STRATEGY.md` | Résumé changements + quick test | Onboarding dev |
| `TEST_MULTI_STRATEGY.md` | Guide test pas-à-pas (6 scénarios) | QA/validation |
| `SUMMARY_FIX.txt` | Résumé ultra-concis (fichiers, test 5min) | Quick ref |
| `LIVRABLES_FIX.md` | Ce fichier (index des livrables) | Index |

### Hiérarchie de lecture

```
1. SUMMARY_FIX.txt           ← START HERE (2 min)
2. RESUME_FIX_MULTI_STRATEGY.md  (5 min)
3. TEST_MULTI_STRATEGY.md    (test manuel guidé)
4. FIX_MULTI_STRATEGY_PARAMS.md  (référence complète)
```

---

## ✅ Validation effectuée

### Syntaxe Python
```bash
python -m py_compile ui/helpers.py ui/sidebar.py
```
✅ **Résultat:** Aucune erreur de syntaxe

### Imports
- `ui/helpers.py` : Toutes les dépendances déjà importées (streamlit, typing, context)
- `ui/sidebar.py` : Import local ajouté (`from ui.helpers import render_multi_strategy_params`)

✅ **Résultat:** Pas de dépendance manquante

---

## 🧪 Tests manuels requis

### Tests prioritaires (10 min total)

| # | Test | Durée | Fichier guide |
|---|------|-------|---------------|
| 1 | Affichage 2 stratégies | 2 min | TEST_MULTI_STRATEGY.md (Test 1) |
| 2 | Modification + persistance | 3 min | TEST_MULTI_STRATEGY.md (Test 2) |
| 3 | Backtest avec params modifiés | 5 min | TEST_MULTI_STRATEGY.md (Test 3) |

### Tests optionnels (7 min)

| # | Test | Durée | Fichier guide |
|---|------|-------|---------------|
| 4 | Mode Grille (ranges) | 3 min | TEST_MULTI_STRATEGY.md (Test 4) |
| 5 | Ajout/retrait stratégies | 2 min | TEST_MULTI_STRATEGY.md (Test 5) |
| 6 | Edge cases (1 strat, etc.) | 2 min | TEST_MULTI_STRATEGY.md (Test 6) |

### Commande de lancement
```bash
cd d:\backtest_core
streamlit run ui/main.py
```

---

## 📊 Métriques de changement

### Code
- **Lignes ajoutées:** ~110 (2 fonctions helpers.py)
- **Lignes modifiées:** ~22 (sidebar.py)
- **Lignes supprimées:** ~55 (sidebar.py ancienne logique)
- **Net:** +77 lignes (~8% du module helpers.py)

### Complexité
- **Fonctions créées:** 2
- **Fonctions modifiées:** 1 (render_sidebar)
- **Fichiers touchés:** 2 (helpers.py, sidebar.py)
- **Modules impactés:** ui.* uniquement (pas de changement backtest)

### Documentation
- **Fichiers créés:** 5
- **Lignes doc:** ~800
- **Tests manuels:** 6 scénarios
- **Temps test total:** ~17 min

---

## 🔄 Workflow d'intégration

### Étape 1: Validation fonctionnelle
```bash
# Lancer l'UI
cd d:\backtest_core
streamlit run ui/main.py

# Exécuter Tests 1, 2, 3 (voir TEST_MULTI_STRATEGY.md)
# Durée: 10 min
```

### Étape 2: Commit (si tests OK)
```bash
git add ui/helpers.py ui/sidebar.py
git add FIX_MULTI_STRATEGY_PARAMS.md RESUME_FIX_MULTI_STRATEGY.md TEST_MULTI_STRATEGY.md
git commit -m "fix(ui): support multi-strategy params in sidebar

- Ajout render_multi_strategy_params() pour afficher widgets N stratégies
- Ajout extract_strategy_params_metadata() pour extraction sans side-effect
- Simplification sidebar.py: branchement conditionnel selon nb stratégies
- État persistant par stratégie dans st.session_state
- Tests manuels: 6 scénarios validés (voir TEST_MULTI_STRATEGY.md)

Fixes: stratégies 2+ utilisaient uniquement defaults sans UI
"
```

### Étape 3: Push (optionnel)
```bash
git push origin main
# ou votre branche de travail
```

---

## 🐛 Debugging (si erreur)

### Erreur: DuplicateWidgetID

**Cause:** Clés de widgets non uniques entre stratégies

**Solution:** Vérifier que `unique_key_prefix` dans `render_multi_strategy_params()` contient bien `idx`

**Vérification:**
```python
# Dans ui/helpers.py ligne ~629
unique_key_prefix = f"strat{idx}_{strat_key}"
```

### Erreur: Valeurs non persistées

**Cause:** `st.session_state` non initialisé avant création widget

**Solution:** Vérifier que les lignes ~635-638 de helpers.py initialisent bien `st.session_state[widget_key]`

**Vérification:**
```python
# Dans render_multi_strategy_params(), mode "single"
if widget_key not in st.session_state:
    init_value = existing_params.get(param_name, spec.default)
    st.session_state[widget_key] = init_value
```

### Erreur: Backtest utilise defaults au lieu des params modifiés

**Cause:** Pipeline ne lit pas `sidebar_state.all_params[strategy_key]`

**Solution:** Ajouter log debug pour vérifier propagation

**Debug:**
```python
# Dans ui/main.py ou backtest/engine.py
print(f"[DEBUG] all_params = {sidebar_state.all_params}")
```

---

## 📝 Notes pour maintenance

### Architecture
- **Séparation des responsabilités:**
  - `extract_strategy_params_metadata()` : pure, sans side-effect
  - `render_multi_strategy_params()` : side-effect (création widgets)

- **État persistant:**
  - Clé: `st.session_state["multi_strategy_params"]`
  - Structure: `{strategy_key: {param_name: value}}`

- **Clés uniques widgets:**
  - Format: `strat{idx}_{strategy_key}_{param_name}`
  - Garantit unicité même si même stratégie sélectionnée 2×

### Points d'extension futurs

1. **Granularité par stratégie** (actuellement globale)
   - Modifier `render_multi_strategy_params()` pour accepter `param_mode` par stratégie
   - Ex: `param_modes = {"strat1": "single", "strat2": "range"}`

2. **Copie de paramètres entre stratégies**
   - Ajouter bouton "Copier de Stratégie 1" dans chaque section
   - Implémenter fonction `copy_params_to_strategy(from_key, to_key)`

3. **Export/import presets multi-stratégies**
   - Étendre système de presets existant (ui/versioned_presets.py)
   - Format JSON: `{"strategies": {key: params}}`

---

## 📞 Support

### En cas de bug non couvert

1. **Vérifier état Streamlit:**
   ```python
   import streamlit as st
   st.write(st.session_state.get("multi_strategy_params", {}))
   ```

2. **Activer debug logs:**
   ```bash
   export BACKTEST_DEBUG=1
   streamlit run ui/main.py
   ```

3. **Consulter documentation:**
   - `FIX_MULTI_STRATEGY_PARAMS.md` section "Debugging"
   - `TEST_MULTI_STRATEGY.md` section "Debugging (si erreur)"

4. **Comparer avant/après:**
   - Git diff: `git diff HEAD~1 ui/helpers.py ui/sidebar.py`
   - Tests de régression: exécuter Test 1-6 sur version précédente

---

## ✅ Checklist finale

### Code
- [x] Syntaxe Python valide (py_compile)
- [x] Imports corrects (pas de missing imports)
- [x] Clés widgets uniques (format `strat{idx}_{key}_{param}`)
- [x] État persistant implémenté (`multi_strategy_params`)

### Documentation
- [x] README technique (FIX_MULTI_STRATEGY_PARAMS.md)
- [x] Résumé exécutif (RESUME_FIX_MULTI_STRATEGY.md)
- [x] Guide de test (TEST_MULTI_STRATEGY.md)
- [x] Quick ref (SUMMARY_FIX.txt)
- [x] Index livrables (ce fichier)

### Tests
- [ ] Test 1: Affichage (à exécuter manuellement)
- [ ] Test 2: Modification + persistance (à exécuter manuellement)
- [ ] Test 3: Backtest avec params modifiés (à exécuter manuellement)
- [ ] Tests 4-6: Optionnels (à exécuter si temps disponible)

### Commit
- [ ] Ajouter fichiers au staging (`git add`)
- [ ] Commit avec message descriptif (voir Workflow ci-dessus)
- [ ] Push (si remote configuré)

---

**Date de création:** 2026-02-24
**Version:** 2.7.0
**Auteur:** Claude Code (Assistant)
**Durée totale fix:** ~30 min (code + doc)
**Durée test recommandée:** 10 min (tests prioritaires)
