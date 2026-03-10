# 🔧 FIX: Régression de performance (2600 → 317 runs/s)

## Problème identifié

Performance dégradée de **8× plus lente** après "optimisations" erronées:
- **Avant**: 2600 runs/seconde (5M combos en 50 minutes)
- **Après**: 317 runs/seconde (133K combos avant crash)

## Régressions corrigées dans ui/main.py

### 1. ⚠️ CRITIQUE: Timeout wait() trop court (ligne ~1220)

**Erreur**: Quelqu'un a pensé que réduire le timeout rendrait le système plus rapide.

```python
# ❌ VERSION CASSÉE (actuelle avant fix)
# ✅ FIX #2: Réduire timeout de 0.5s à 0.05s (10× plus rapide)
done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
```

**Pourquoi c'est faux**:
- Timeout 0.05s (50ms) → boucle tourne 10× plus vite
- Consomme du CPU inutilement sur le thread principal
- Crée de la **contention CPU** avec les workers
- Sature le **GIL Python** (Global Interpreter Lock)
- Les workers sont **ralentis** car le thread principal prend trop de CPU

**Fix appliqué**:
```python
# ✅ VERSION CORRIGÉE
# Timeout optimal: 500ms (équilibre entre réactivité et contention CPU)
done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
```

### 2. ⚠️ IMPORTANT: max_inflight trop élevé (ligne ~1155)

**Erreur**: Augmentation de la queue de 2× à 8× le nombre de workers.

```python
# ❌ VERSION CASSÉE
# ✅ FIX #1: Augmenter max_inflight pour alimenter tous les workers
# Après: n_workers × 8 = 192 tâches pour 24 workers
max_inflight = max(1, min(total_runs, n_workers_effective * 8))
```

**Pourquoi c'est problématique**:
- 192 tâches soumises en avance pour 24 workers
- Saturation de la queue du ProcessPoolExecutor
- Contention mémoire (toutes les tâches en mémoire)
- Les workers ne peuvent pas travailler efficacement

**Fix appliqué**:
```python
# ✅ VERSION CORRIGÉE
# Max inflight: n_workers × 2 (évite saturation queue)
# 24 workers → 48 tâches max en parallèle
max_inflight = max(1, min(total_runs, n_workers_effective * 2))
```

### 3. ℹ️ MINEUR: Fréquence d'affichage incohérente (ligne ~1355)

**Erreur**: Affichage toutes les 5 secondes au lieu de 2 secondes.

```python
# ❌ VERSION CASSÉE
if completed % 100 == 0 or current_time - last_render_time >= 5.0 or completed == 1:
```

**Fix appliqué**:
```python
# ✅ VERSION CORRIGÉE
# Affichage équilibré: tous les 100 runs ou toutes les 2 secondes
if completed % 100 == 0 or current_time - last_render_time >= 2.0 or completed == 1:
```

## Impact attendu

Restauration de la performance originale:
- **Cible**: 2600 runs/seconde
- **Gain**: 8× plus rapide qu'avant le fix
- **Stabilité**: Pas de crash BrokenProcessPool après 133K runs

## Leçon apprise

❌ **NE PAS** réduire les timeouts de wait() en pensant que ça va plus vite
✅ **TOUJOURS** profiler avant d'optimiser
✅ **COMPRENDRE** que le multiprocessing nécessite du temps CPU pour les workers

L'optimisation prématurée est la racine de tous les maux. - Donald Knuth
