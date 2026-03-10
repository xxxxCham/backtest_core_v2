# Correction Optuna - Métriques Silencieusement Manquantes

**Date**: 2026-01-06
**Problème**: Optuna retourne `value=0.0` pour tous les trials → optimisation impossible

---

## 🔍 Diagnostic du Problème

### Symptômes Observés

```csv
# Fichier: 000.csv (10 trials Optuna)
trial,value,bb_period,bb_std,atr_period,atr_mult
0,0.0,25,2.1,14,1.8
1,0.0,30,1.9,20,2.2
2,0.0,18,2.5,10,1.5
...
9,0.0,22,2.3,16,1.9
```

**Observation critique**: `value` est **exactement 0.0** pour **10/10 trials** malgré des paramètres différents.

### Cause Racine Identifiée

**Fichier**: `backtest/optuna_optimizer.py`

#### 1. **Multi-Objectif - Ligne 672** ❌ (AVANT)

```python
# MAUVAIS: Retourne 0 silencieusement si métrique absente
values = [result.metrics.get(m, 0) for m in metrics]
return values
```

**Scénario d'échec**:
- Utilisateur demande métrique `"sharpe"` (typo, devrait être `"sharpe_ratio"`)
- `.get("sharpe", 0)` → retourne `0` au lieu de crash
- Optuna reçoit `value=0.0` pour tous les trials
- Optimisation impossible (aucun signal d'apprentissage)

#### 2. **Single-Objectif** ✅ (Déjà correct)

```python
# BON: Crash explicite si métrique absente (ligne 428-436)
if metric not in result.metrics:
    available = ", ".join(sorted(result.metrics.keys()))
    msg = f"Optuna metric '{metric}' not found. Available: [{available}]"
    raise KeyError(msg)

value = float(result.metrics[metric])
```

---

## ✅ Corrections Appliquées

### 1. **Multi-Objectif Strict** (lignes 690-702)

```python
# APRÈS: Validation stricte + crash explicite
values = []
for m in metrics:
    if m not in result.metrics:
        available = ", ".join(sorted(result.metrics.keys()))
        msg = (
            f"Multi-objective metric '{m}' not found in result.metrics. "
            f"Available metrics: [{available}]. "
            f"trial={trial.number} params={params}"
        )
        self.logger.error(msg)
        raise KeyError(msg)
    values.append(float(result.metrics[m]))
```

**Bénéfices**:
- ✅ Crash immédiat si métrique manquante
- ✅ Log des métriques disponibles pour debug
- ✅ Message d'erreur explicite avec contexte (trial, params)

### 2. **Logging Métriques Disponibles** (lignes 418-425, 681-688)

**Single-Objectif**:
```python
# Log au premier trial pour visibilité
if trial.number == 0:
    available_metrics = sorted(result.metrics.keys())
    self.logger.info(
        "trial_0_metrics_available count=%s metrics=[%s]",
        len(available_metrics),
        ", ".join(available_metrics)
    )
```

**Multi-Objectif**:
```python
# Log au premier trial
if trial.number == 0:
    available_metrics = sorted(result.metrics.keys())
    self.logger.info(
        "multi_obj_trial_0_metrics count=%s metrics=[%s]",
        len(available_metrics),
        ", ".join(available_metrics)
    )

# Log des valeurs extraites (debug)
self.logger.debug(
    "trial_%s metrics_extracted %s",
    trial.number,
    dict(zip(metrics, values))
)
```

**Bénéfices**:
- ✅ Visibilité immédiate des métriques calculées
- ✅ Debug facile des typos dans noms de métriques
- ✅ Validation que le backtest génère bien les métriques attendues

---

## 📊 Métriques Disponibles (Référence)

### Liste Complète (depuis `metrics_types.py`)

```python
PerformanceMetricsPct = {
    "total_pnl": float,              # PnL total ($)
    "total_return_pct": float,       # Return total (%)
    "annualized_return": float,      # Return annualisé (%)
    "cagr": float,                   # CAGR (%)
    "sharpe_ratio": float,           # Sharpe ratio
    "sortino_ratio": float,          # Sortino ratio
    "calmar_ratio": float,           # Calmar ratio
    "max_drawdown_pct": float,       # Max drawdown (%)
    "volatility_annual": float,      # Volatilité annualisée (%)
    "total_trades": int,             # Nombre de trades
    "win_rate_pct": float,           # Win rate (%)
    "profit_factor": float,          # Profit factor
    "expectancy": float,             # Expectancy moyenne
}
```

### Métriques Supplémentaires (Tier S, optionnelles)

```python
# Activées avec include_tier_s=True
"sqn": float,                        # System Quality Number
"recovery_factor": float,            # Recovery factor
"max_drawdown_duration_days": float, # Durée max DD (jours)
"account_ruined": bool,              # Compte ruiné (equity <= 0)
```

### Noms Corrects vs Erreurs Communes

| ✅ Correct | ❌ Erreur Commune |
|-----------|------------------|
| `sharpe_ratio` | `sharpe`, `sharpe_r` |
| `total_return_pct` | `total_return`, `return_pct` |
| `max_drawdown_pct` | `max_dd`, `drawdown` |
| `win_rate_pct` | `win_rate`, `winrate` |
| `profit_factor` | `pf`, `profit_f` |

---

## 🧪 Tests Recommandés

### 1. Test Single-Objectif

```python
from backtest.optuna_optimizer import OptunaOptimizer
import pandas as pd

# Charger données
df = pd.read_csv("data/BTCUSDC_30m.csv", parse_dates=["datetime"], index_col="datetime")

# Optimiseur
optimizer = OptunaOptimizer(
    strategy_name="bollinger_atr",
    data=df,
    param_space={
        "bb_period": {"type": "int", "low": 10, "high": 50},
        "bb_std": {"type": "float", "low": 1.5, "high": 3.0, "step": 0.1},
    },
)

# Test avec métrique VALIDE
result = optimizer.optimize(
    n_trials=5,
    metric="sharpe_ratio",  # ✅ CORRECT
    show_progress=True
)

print(result.summary())
```

**Sortie attendue** (logs):
```
INFO: trial_0_metrics_available count=13 metrics=[annualized_return, cagr, calmar_ratio, ...]
INFO: optimization_end duration=12.3s best_sharpe_ratio=1.234
```

### 2. Test avec Métrique INVALIDE (vérifier crash explicite)

```python
# Test avec métrique INVALIDE (devrait crasher)
try:
    result = optimizer.optimize(
        n_trials=5,
        metric="sharpe",  # ❌ INVALIDE (typo)
    )
except KeyError as e:
    print(f"✅ Erreur attendue: {e}")
    # Sortie: "Optuna metric 'sharpe' not found. Available: [sharpe_ratio, ...]"
```

### 3. Test Multi-Objectif

```python
# Multi-objectif avec métriques VALIDES
result = optimizer.optimize_multi_objective(
    n_trials=10,
    metrics=["sharpe_ratio", "max_drawdown_pct"],  # ✅ CORRECT
    directions=["maximize", "minimize"],
)

print(f"Pareto front: {len(result.pareto_front)} solutions")
```

---

## 🐛 Scénarios de Debug

### Scénario 1: Tous les trials à 0.0

**Symptôme**:
```csv
trial,value,bb_period,bb_std
0,0.0,25,2.1
1,0.0,30,1.9
```

**Diagnostic**:
1. Vérifier les logs au trial 0:
   ```
   INFO: trial_0_metrics_available count=13 metrics=[...]
   ```
2. Vérifier que la métrique demandée est dans la liste
3. Si absente → typo dans le nom

**Solution**:
- Corriger le nom de métrique
- Utiliser exactement les noms de `PerformanceMetricsPct`

### Scénario 2: Sharpe ratio toujours 0.0

**Symptôme**:
```
trial_0 sharpe_ratio=0.00
trial_1 sharpe_ratio=0.00
```

**Causes possibles**:
1. **Return nul** : Stratégie ne génère aucun trade
2. **Volatilité infinie** : Équity constante (denominator = 0)
3. **Données insuffisantes** : < 2 barres de données

**Debug**:
```python
# Ajouter après run()
result = engine.run(...)
print(f"Total trades: {result.metrics.get('total_trades', 0)}")
print(f"Total return: {result.metrics.get('total_return_pct', 0):.2f}%")
print(f"Sharpe: {result.metrics.get('sharpe_ratio', 0):.4f}")

if result.metrics.get('total_trades', 0) == 0:
    print("⚠️ Aucun trade généré → Sharpe = 0")
```

### Scénario 3: KeyError après correction

**Symptôme**:
```
ERROR: Optuna metric 'custom_metric' not found in result.metrics.
Available metrics: [sharpe_ratio, total_return_pct, ...]
```

**Cause**: Métrique personnalisée non implémentée dans `calculate_metrics()`

**Solution**:
1. Utiliser une métrique standard OU
2. Modifier `backtest/performance.py:calculate_metrics()` pour ajouter la métrique

---

## 📈 Impact Attendu

### Avant (MAUVAIS)
- ❌ Optuna reçoit `value=0` silencieusement
- ❌ Optimisation impossible (pas de signal)
- ❌ Perte de temps (trials inutiles)
- ❌ Aucun feedback utilisateur

### Après (BON)
- ✅ Crash explicite au premier trial si métrique manquante
- ✅ Message d'erreur clair avec métriques disponibles
- ✅ Logs au trial 0 pour validation
- ✅ Debug facile (typos détectés immédiatement)

---

## 🔗 Fichiers Modifiés

| Fichier | Lignes | Modification |
|---------|--------|--------------|
| `backtest/optuna_optimizer.py` | 418-425 | Logging métriques trial 0 (single) |
| `backtest/optuna_optimizer.py` | 427-436 | Validation stricte (déjà présent) |
| `backtest/optuna_optimizer.py` | 681-711 | Logging + validation stricte (multi) |

---

## 💡 Recommandations

### 1. Toujours vérifier les logs au démarrage

```bash
# Lancer optimisation avec logging
python test_optuna.py 2>&1 | tee optuna_run.log

# Vérifier les métriques disponibles
grep "trial_0_metrics_available" optuna_run.log
```

### 2. Utiliser les noms exacts de métriques

```python
# ✅ BON: Copier-coller depuis PerformanceMetricsPct
metric = "sharpe_ratio"

# ❌ MAUVAIS: Écrire à la main (risque de typo)
metric = "sharpe"  # Manquant "_ratio"
```

### 3. Tester avec n_trials=1 d'abord

```python
# Valider la configuration avant run complet
result = optimizer.optimize(n_trials=1, metric="sharpe_ratio")
print(result.best_value)  # Doit être != 0 (sauf si vraiment Sharpe=0)
```

### 4. Investiguer si PnL catastrophique

**Si tous les backtests donnent PnL négatif** (-260% dans votre cas):
1. Vérifier les frais de transaction (trop élevés?)
2. Vérifier le slippage (trop pessimiste?)
3. Vérifier la logique de stratégie (signaux inversés?)
4. Analyser quelques trades individuels (prix entry/exit cohérents?)

---

**Corrections appliquées le**: 2026-01-06
**Validé par**: Claude Sonnet 4.5
**Prochaine étape**: Investiguer le PnL catastrophique (voir fichier `BACKTEST_PNL_INVESTIGATION.md`)
