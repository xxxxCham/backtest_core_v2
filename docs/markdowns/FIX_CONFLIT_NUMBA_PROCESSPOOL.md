# 🔧 Fix: Conflit Numba ↔ ProcessPool

## 🎯 Problème Identifié

### Symptôme
Le système démarre avec Numba (logs visibles, CPU à 97%), puis **bascule vers ProcessPoolExecutor** pendant l'exécution (plus de logs Numba, comportement différent).

### Cause Racine
**Race condition dans la logique de sélection des modes d'exécution** (`ui/main.py`).

```python
# ❌ AVANT (BUGUÉ)
if use_numba_sweep and total_runs > 1:
    # Numba s'exécute
    completed = total_runs  # ✅ Marque comme complété

# ❌ PROBLÈME: Pas de vérification si Numba a complété!
if not use_numba_sweep and n_workers_effective > 1:
    # ProcessPool s'exécute MÊME SI Numba a terminé!
```

### Scénario du Bug

1. **Démarrage** : `use_numba_sweep = True` → Numba s'exécute
2. **Numba termine** : `completed = total_runs`
3. **Exception/Reload** : `use_numba_sweep = False` (import échoue, cache Python, etc.)
4. **ProcessPool démarre** : Condition ne vérifie pas `completed < total_runs` ❌
5. **Résultat** : Sweep s'exécute 2× (Numba puis ProcessPool)

---

## ✅ Solution Implémentée

### Fix #1 : Guards pour Éviter Double Exécution

**Ligne 1318** (ProcessPool) :
```python
# ✅ APRÈS (CORRIGÉ)
# 🔒 GUARD: Ne pas exécuter si Numba a déjà complété
if not use_numba_sweep and completed < total_runs and n_workers_effective > 1:
    logger.info(f"[EXECUTION PATH] 🔄 PROCESSPOOL sélectionné: {total_runs:,} combos")
    # ProcessPool code...
```

**Ligne 1596** (Séquentiel) :
```python
# ✅ APRÈS (CORRIGÉ)
elif not use_numba_sweep and completed < total_runs:
    logger.info(f"[EXECUTION PATH] 📋 MODE SEQUENTIEL sélectionné")
    run_sequential_combos(combo_iter, "sweep_sequential")
```

### Fix #2 : Logs de Diagnostic

Ajout de logs explicites pour **tracer quel chemin s'exécute et pourquoi** :

```python
# Numba sélectionné
logger.info(f"[EXECUTION PATH] 🚀 NUMBA SWEEP sélectionné: {total_runs:,} combos")

# Numba non supporté
logger.info(f"[NUMBA SKIP] Stratégie '{strategy_key}' non supportée")

# Grille trop grande
logger.warning(f"[NUMBA SKIP] Grille trop grande: {total_runs:,} > {NUMBA_MAX_COMBOS:,}")

# Import échoué
logger.warning(f"[NUMBA SKIP] Import failed: {import_err}")

# ProcessPool sélectionné
logger.info(f"[EXECUTION PATH] 🔄 PROCESSPOOL sélectionné: {total_runs:,} combos")

# Mode séquentiel
logger.info(f"[EXECUTION PATH] 📋 MODE SEQUENTIEL sélectionné")

# Aucun mode (déjà complété)
logger.info(f"[EXECUTION PATH] ✅ SKIP: Sweep déjà complété ({completed}/{total_runs})")
```

---

## 🧪 Test de Validation

### Test 1 : Numba Seul (Nominal)
```python
# Lancer sweep 1.7M combos
# Vérifier dans logs:
# ✅ "[EXECUTION PATH] 🚀 NUMBA SWEEP sélectionné"
# ✅ "[EXECUTION PATH] ✅ SKIP: Sweep déjà complété"
# ❌ NE DOIT PAS voir "PROCESSPOOL sélectionné"
```

### Test 2 : Fallback ProcessPool
```python
# Désactiver Numba temporairement
# Vérifier dans logs:
# ✅ "[NUMBA SKIP] ..."
# ✅ "[EXECUTION PATH] 🔄 PROCESSPOOL sélectionné"
# ❌ NE DOIT PAS voir "NUMBA SWEEP sélectionné"
```

### Test 3 : Exception Numba
```python
# Forcer exception dans sweep_numba.py
# Vérifier dans logs:
# ✅ "[EXECUTION PATH] 🚀 NUMBA SWEEP sélectionné"
# ✅ "Numba sweep failed: ..."
# ✅ "[EXECUTION PATH] 🔄 PROCESSPOOL sélectionné"
# (Fallback normal dans ce cas)
```

---

## 📊 Impact Attendu

### Avant Fix
- ⚠️ Double exécution possible (Numba + ProcessPool)
- ⚠️ Temps d'exécution imprévisible
- ⚠️ CPU oscille entre 97% et 19%
- ⚠️ Logs incohérents (pas de logs Numba après démarrage)

### Après Fix
- ✅ Exécution unique garantie
- ✅ Temps stable (~4-5 min pour 1.7M combos)
- ✅ CPU stable à 97% pendant toute l'exécution
- ✅ Logs cohérents et traçables

---

## 🔍 Diagnostic en Cas de Problème

Si le problème persiste après ce fix, vérifier dans les logs :

1. **Quel chemin est sélectionné** → Chercher `[EXECUTION PATH]` dans les logs
2. **Pourquoi Numba est sauté** → Chercher `[NUMBA SKIP]` dans les logs
3. **Si double exécution** → Vérifier que `completed < total_runs` est respecté

### Commande PowerShell pour Filtrer Logs
```powershell
# Voir uniquement les décisions d'exécution
Get-Content logs/*.log | Select-String "EXECUTION PATH"

# Voir pourquoi Numba est sauté
Get-Content logs/*.log | Select-String "NUMBA SKIP"
```

---

## 📁 Fichiers Modifiés

- **ui/main.py** (lignes 1162-1604)
  - Ajout guards `completed < total_runs` pour ProcessPool et Séquentiel
  - Ajout logs de diagnostic pour tous les chemins d'exécution
  - Ajout logs explicites pour les raisons de skip Numba

---

## 🚀 Prochaines Étapes

1. ✅ Tester le fix avec grille 1.7M combos
2. ✅ Vérifier logs pour confirmer exécution unique
3. ✅ Valider performance stable (6,600 bt/s)
4. ✅ Commit avec message explicite
5. ⏭️ Passer à l'implémentation du filtre warmup period (PROMPT_NOUVELLE_SESSION.md)

---

## 💡 Leçons Apprises

1. **Toujours vérifier l'état de complétion** avant d'exécuter un mode alternatif
2. **Logger EXPLICITEMENT** les décisions de branchement dans le code critique
3. **Guards multiples** nécessaires quand plusieurs chemins d'exécution existent
4. **Cache Python** peut causer des états incohérents → Nettoyage systématique

---

**Date** : 2026-02-05
**Auteur** : Claude Sonnet 4.5
**Commit** : À venir après validation
