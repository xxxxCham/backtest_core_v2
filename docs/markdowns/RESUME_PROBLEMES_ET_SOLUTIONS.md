# 📋 Résumé des Problèmes et Solutions - Session 2026-02-05

## 🎯 Contexte

**Objectif** : Optimiser un système de backtesting pour sweeps massifs (1.7M+ combos) et analyser les résultats pour construire une stratégie robuste.

---

## ✅ Problèmes Résolus

### 1. **Sweep Numba Bloquait Après Kernel (10+ min)**

**Symptôme** :
- Kernel Numba terminait en 4-5 min
- Construction des résultats bloquait 10+ minutes
- CPU inactif, aucun feedback

**Cause** :
- Boucle Python pure sur 1.7M éléments
- List comprehension lente pour créer les dicts de résultats

**Solution** :
- ✅ Construction vectorisée par batch (10K)
- ✅ Feedback progressif tous les 100K combos
- ✅ Performance : 1.96s pour 1.7M résultats (au lieu de 10+ min)

**Fichiers modifiés** :
- `backtest/sweep_numba.py` (lignes 1067-1140)
- `ui/main.py` (lignes 1205-1283)

---

### 2. **Cache Python Après Redémarrage**

**Symptôme** :
- Après reboot, performance retombait à 140 bt/s (au lieu de 6,600 bt/s)
- Optimisations non chargées

**Cause** :
- Cache Python (`.pyc`, `__pycache__`) contenait l'ancien code
- Streamlit rechargeait les anciens modules

**Solution** :
- ✅ Script `run_streamlit.bat` nettoie automatiquement les caches
- ✅ Nettoyage de `.pyc`, `__pycache__`, cache Numba, cache Streamlit

**Fichier modifié** :
- `run_streamlit.bat` (lignes 39-43)

---

### 3. **Nettoyage des Scripts de Lancement**

**Symptôme** :
- 10 fichiers `.bat` à la racine → confusion

**Solution** :
- ✅ Archivage de 7 anciens scripts dans `scripts_old/`
- ✅ Conservation de 3 scripts essentiels :
  - `run_streamlit.bat` (lanceur principal optimisé)
  - `install.bat`
  - `edit_ranges.bat`

---

## ⚠️ Problèmes En Cours

### 4. **Extraction de Paramètres Lente (1.7M combos)**

**Symptôme** :
- CPU stagnant à 50-60% pendant extraction
- Pas de feedback, impression de freeze
- 10-30 secondes de silence

**Cause** :
- List comprehension Python sur 1.7M éléments × 5 paramètres = 8.5M opérations

**Solution appliquée** :
- ✅ Extraction avec feedback tous les 100K combos
- ✅ Pré-allocation des arrays NumPy

**Fichier modifié** :
- `backtest/sweep_numba.py` (lignes 1004-1022)

---

### 5. **Paramètres Sans Impact sur Résultats**

**Symptôme** :
- Top 10 combos ont EXACTEMENT les mêmes résultats
- Mais paramètres différents (bb_std, atr_period, atr_percentile)

**Cause** :
```python
# bb_std récupéré mais JAMAIS utilisé
bb_std = bb_stds[combo_idx]  # ✅ Récupéré
z_score = (closes[i] - sma) / std  # ❌ Devrait être : / (std * bb_std)

# atr_period et atr_percentile extraits mais JAMAIS passés au kernel
```

**Impact** :
- Seuls `bb_period`, `entry_z`, `k_sl`, `leverage` ont un effet réel
- Les autres paramètres sont inutiles (grille mal dimensionnée)

**Solution à implémenter** :
- [ ] Corriger l'utilisation de `bb_std` dans le calcul du z-score
- [ ] OU retirer les paramètres inutiles de la grille

**Fichier à modifier** :
- `backtest/sweep_numba.py` (lignes 113-140)

---

### 6. **Gains Artificiels sur Données de Listing (CRITIQUE)**

**Symptôme** :
- Stratégie génère +444% de gains
- Mais : gains accumulés pendant 2020-2024, pertes en 2024-2026
- Courbe d'équité monte fort au début puis descend

**Cause IDENTIFIÉE** :
```
Première barre (2020-09-22 06:30) : 0.85$ → 6.00$ en 15 min (+605% !)
Premières heures : Range 0.85$ - 7.00$ = +723%
Volume : 50× plus élevé que données récentes
Mouvements > 20% : 1% des bars (vs 0% aujourd'hui)
```

**Explication** :
- Phase de **price discovery** du listing AVAX
- Volatilité anormale, prix irréalistes
- La stratégie "trade" sur ces gaps artificiels
- Résultat : PnL positif mais **totalement invalide**

**Solutions possibles** :

#### Option A : Filtrage Temporel (RECOMMANDÉ)
```python
# Ignorer les N premières heures/jours après listing
listing_date = "2020-09-22"
warmup_hours = 24  # ou 48, 72

df = df[df['datetime'] > listing_date + pd.Timedelta(hours=warmup_hours)]
```

#### Option B : Filtrage par Volume
```python
# Détecter stabilisation du volume
volume_ma = df['volume'].rolling(100).mean()
stable_volume = df['volume'] < volume_ma * 2  # Éliminer pics anormaux

df = df[stable_volume]
```

#### Option C : Filtrage par Volatilité
```python
# Calculer volatilité réalisée
df['volatility'] = df['close'].pct_change().rolling(20).std()

# Exclure périodes de volatilité anormale
max_vol = df['volatility'].quantile(0.95)
df = df[df['volatility'] < max_vol]
```

**Fichiers à modifier** :
- `ui/sidebar.py` (ajouter option "Warmup Period")
- `ui/main.py` (appliquer filtre avant backtest)

---

## 📊 Performance Actuelle

### Sweep Numba Optimisé
```
Configuration : 1,771,561 combos × 125,031 bars
CPU           : Ryzen 9950X (32 threads)
RAM           : 60GB DDR5

Performance   :
  - Kernel Numba    : 266.97s (6,636 bt/s)
  - Construction    : 1.96s
  - TOTAL           : 268.93s (~4.5 min)
  - Throughput      : 6,587 bt/s

Amélioration : 300× speedup sur construction (10 min → 2s)
```

### Comparaison Avant/Après
| Phase | Avant | Après | Gain |
|-------|-------|-------|------|
| Kernel Numba | 274s | 267s | ~3% |
| Construction | 10+ min | 2s | **300×** |
| Feedback | Aucun | Tous les 100K | ✅ |
| Total | 400+ s | 269s | 33% |

---

## 🚀 Prochaines Étapes

### Phase 1 : Corriger les Bugs Identifiés
1. [ ] Corriger utilisation de `bb_std` dans kernel Numba
2. [ ] Ajouter filtrage des données de listing (warmup period)
3. [ ] Tester avec données filtrées

### Phase 2 : Analyse des Régimes de Marché
1. [ ] Utiliser script `analyze_winning_conditions.py`
2. [ ] Identifier quand la stratégie gagne/perd
3. [ ] Créer filtres de régime (volatilité, tendance, volume)

### Phase 3 : Stratégie Finale
1. [ ] Construire règles pour trader SEULEMENT dans zones favorables
2. [ ] Walk-forward analysis sur périodes séparées
3. [ ] Validation out-of-sample

---

## 📁 Fichiers Clés

### Scripts Optimisés
- `run_streamlit.bat` - Lanceur avec nettoyage automatique des caches
- `backtest/sweep_numba.py` - Sweep Numba optimisé
- `ui/main.py` - UI avec conversion batch optimisée

### Outils d'Analyse
- `labs/analysis/analyze_winning_conditions.py` - Analyse trades gagnants/perdants
- `labs/visualization/parameter_heatmap.py` - Visualisation heatmap des paramètres

### Documentation
- `REDEMARRAGE.md` - Guide de redémarrage après reboot
- `NETTOYAGE_SCRIPTS.md` - Doc des scripts nettoyés
- `FILTRE_DATE_LISTING.md` - Guide de filtrage des données

---

## 🔧 Configuration Optimale

### Variables d'Environnement (`run_streamlit.bat`)
```batch
NUMBA_NUM_THREADS=32       # Tous les threads CPU
NUMBA_THREADING_LAYER=omp  # OpenMP pour parallélisme
OMP_NUM_THREADS=32         # Threads OpenMP
MKL_NUM_THREADS=1          # Éviter nested parallelism
BACKTEST_USE_GPU=0         # CPU uniquement (optimal pour backtesting)
```

### Performance Attendue
- **Petits sweeps (< 10K)** : ~4,000-5,000 bt/s
- **Gros sweeps (100K-1M)** : ~6,000-7,000 bt/s
- **Très gros sweeps (1M+)** : ~6,500-7,000 bt/s

---

## 💡 Leçons Apprises

1. **Numba est optimal pour backtesting** (vs GPU qui est inadapté)
2. **Construction de résultats Python pure = goulot majeur** → Vectorisation critique
3. **Cache Python après reboot = piège classique** → Nettoyage systématique nécessaire
4. **Données de listing = piège mortel** → Toujours filtrer premières heures/jours
5. **Overfitting sur historique complet = stratégie inutile** → Walk-forward analysis obligatoire

---

## 🎯 Objectif Final

Construire une stratégie qui :
- ✅ Utilise correctement tous les paramètres
- ✅ Trade SEULEMENT dans les régimes favorables
- ✅ Ignore les données de price discovery (listing)
- ✅ Valide sur périodes out-of-sample
- ✅ Génère des gains **réels et reproductibles**
