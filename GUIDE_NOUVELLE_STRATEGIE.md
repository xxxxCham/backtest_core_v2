# Guide : Intégrer une Nouvelle Stratégie

## Vue d'ensemble

Ajouter une stratégie au moteur de backtest nécessite de toucher **3 fichiers** et de respecter un contrat précis sur les signaux, les paramètres et le nommage.

```
strategies/
  base.py                    # Classe abstraite StrategyBase + registre
  __init__.py                # Imports (discovery auto)
  indicators_mapping.py      # Métadonnées UI (label, indicateurs affichés)
  ma_strategie.py            # <-- votre fichier
```

---

## 1. Anatomie d'un fichier stratégie

```python
from typing import Any, Dict, List
import numpy as np
import pandas as pd
from utils.parameters import ParameterSpec
from .base import StrategyBase, register_strategy

@register_strategy("ma_strategie")          # (A) Clé unique snake_case
class MaStrategieStrategy(StrategyBase):     # (B) Classe PascalCase + "Strategy"

    def __init__(self):
        super().__init__(name="Ma Stratégie")  # Nom d'affichage

    # --- (C) Indicateurs requis ---
    @property
    def required_indicators(self) -> List[str]:
        return ["bollinger", "atr"]
        # Valeurs valides: "bollinger", "atr", "ema", "rsi", "macd", "stochastic"

    # --- (D) Paramètres par défaut ---
    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "bb_period": 20,
            "bb_std": 2.0,
            "k_sl": 1.5,
            "leverage": 1,
            "initial_capital": 10000,
        }

    # --- (E) Spécifications pour grid search ---
    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "bb_period": ParameterSpec(
                name="bb_period",        # DOIT matcher la clé du dict
                min_val=10, max_val=50,  # Bornes de l'exploration
                default=20,
                param_type="int",        # "int" | "float"
                description="Période des Bandes de Bollinger",
                optimize=True,           # False = exclu du grid search
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1, max_val=10, default=1,
                param_type="int",
                optimize=False,          # <-- IMPORTANT: fixé, pas optimisé
            ),
        }

    # --- (F) Mapping paramètres → indicateurs ---
    def get_indicator_params(self, indicator_name, params):
        if indicator_name == "bollinger":
            return {
                "period": int(params.get("bb_period", 20)),
                "std_dev": float(params.get("bb_std", 2.0)),
            }
        if indicator_name == "atr":
            return {"period": int(params.get("atr_period", 14))}
        return super().get_indicator_params(indicator_name, params)

    # --- (G) Génération de signaux ---
    def generate_signals(self, df, indicators, params) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        # ... logique ...
        # +1.0 = entrer LONG
        # -1.0 = entrer SHORT
        # 0.0  = pas de signal
        return signals
```

---

## 2. Contrat des signaux (CRITIQUE)

| Valeur | Signification |
|--------|--------------|
| `+1.0` | Signal d'entrée LONG (impulsion) |
| `-1.0` | Signal d'entrée SHORT (impulsion) |
| `0.0`  | Aucun signal |

### Ce que le moteur fait avec vos signaux

```
generate_signals()  →  simulate_trades()  →  equity_curve()  →  metrics
    (vous)              (simulateur)          (moteur)          (moteur)
```

**Le simulateur gère les sorties**, pas votre stratégie :
- **Stop-loss** via `k_sl` (% du prix d'entrée)
- **Stop Bollinger** si vous écrivez `bb_stop_long`/`bb_stop_short` dans le DataFrame
- **Signal inverse** : un -1 clôture un long et ouvre un short
- **Fin de données** : force la clôture

### Erreur courante : retourner un état de position

```python
# MAUVAIS : état continu (1,1,1,1,0,0,-1,-1,...)
signals.iloc[i] = position  # Le simulateur ignore les 1 répétés

# BON : impulsion ponctuelle (0,0,1,0,0,0,-1,0,...)
if entry_condition:
    signals.iloc[i] = 1.0
```

### Nettoyage des signaux consécutifs

Pour éviter les doublons, appliquez ce pattern en fin de `generate_signals` :

```python
diff = np.diff(signals_arr, prepend=0.0)
signals_arr[diff == 0] = 0.0
```

---

## 3. ParameterSpec : les pièges

### Constructeur correct

```python
ParameterSpec(
    name="bb_period",       # Obligatoire, doit matcher la clé
    min_val=10,             # PAS "min" !
    max_val=50,             # PAS "max" !
    default=20,
    param_type="int",       # "int" ou "float"
    step=None,              # Auto-calculé si None
    description="...",
    optimize=True,          # False = exclu du grid
)
```

Le Strategy Builder (sandbox) génère `ParameterSpec(min=..., max=...)` qui provoquera une **TypeError** à l'exécution. Toujours convertir en `min_val`/`max_val`.

### Combinatoire du grid

Le grid est un produit cartésien. Avec `max_values_per_param=4` (défaut) :

| Params optimisables | Combinaisons |
|---------------------|-------------|
| 4 | 256 |
| 5 | 1 024 |
| 6 | 4 096 |
| 7 | 16 384 (cap à 10 000) |
| 8 | 65 536 (refusé) |

**Limite** : `max_total_combinations = 10 000` par défaut.
**Solutions** : augmenter `granularity` (0.5 → 0.7), réduire `max_values_per_param`, ou mettre `optimize=False` sur des params stables.

---

## 4. Mapping des indicateurs

Le moteur calcule les indicateurs AVANT d'appeler `generate_signals()`. Vous recevez le résultat dans le dict `indicators`.

### Convention de préfixes (mapping auto)

La classe de base mappe automatiquement les paramètres par préfixe :

| Indicateur | Préfixe | Exemple param → param indicateur |
|-----------|---------|----------------------------------|
| bollinger | `bb_` | `bb_period` → `period` |
| atr | `atr_` | `atr_period` → `period` |
| rsi | `rsi_` | `rsi_period` → `period` |
| ema | `ema_` | `ema_period` → `period` |
| macd | `macd_` | `macd_fast_period` → `fast_period` |

**Attention** : ce mapping auto passe TOUS les params avec le préfixe. Si vous avez `rsi_overbought`, il sera passé à l'indicateur RSI comme `overbought`, ce qui peut causer des erreurs.

**Recommandation** : toujours surcharger `get_indicator_params()` explicitement.

### Format des indicateurs reçus

```python
indicators["bollinger"]  # dict: {"upper": arr, "middle": arr, "lower": arr}
                          # OU tuple: (upper, middle, lower)
indicators["atr"]        # np.ndarray ou pd.Series
indicators["ema"]        # np.ndarray ou pd.Series
indicators["rsi"]        # np.ndarray ou pd.Series
indicators["macd"]       # dict ou tuple selon version
```

Toujours utiliser `np.nan_to_num()` et vérifier le type (Series vs array).

---

## 5. Fichiers à modifier (checklist)

### 5.1 Créer `strategies/ma_strategie.py`

Votre fichier avec `@register_strategy("ma_strategie")`.

### 5.2 Modifier `strategies/__init__.py`

```python
from .ma_strategie import MaStrategieStrategy

__all__ = [
    # ... existants ...
    "MaStrategieStrategy",
]
```

### 5.3 Modifier `strategies/indicators_mapping.py`

```python
STRATEGY_INDICATORS_MAP: Dict[str, StrategyIndicators] = {
    # ... existants ...

    "ma_strategie": StrategyIndicators(
        name="Ma Stratégie",
        ui_label="📊 Ma Stratégie (Type)",     # Icône + label UI
        required_indicators=["bollinger", "atr"],
        internal_indicators=[],
        description="Description courte pour l'UI",
        ui_indicators=["bollinger", "atr"],
    ),
}
```

La clé `"ma_strategie"` DOIT correspondre à celle de `@register_strategy()`.

---

## 6. Capital et position sizing

### Configuration

```python
# Dans default_params de votre stratégie :
"initial_capital": 10000,   # Capital par trade
"leverage": 1,              # Multiplicateur
```

### Formule du simulateur

```
position_size = leverage * initial_capital / prix_entrée
```

Exemple : leverage=1, capital=10000, BTC à 50000 → 0.2 BTC (notionnel 10000$).

### Contraintes du simulateur

- **Une seule position à la fois** (pas de pyramiding)
- **100% du capital** utilisé par défaut via leverage
- Frais : `fees_bps=10` (0.10%) + `slippage_bps=5` (0.05%) = 0.15% par trade
- La méthode `calculate_position_size()` existe mais n'est PAS utilisée par le simulateur

---

## 7. Mode Grid (sweep) : spécificités

### Architecture parallèle

```
UI (Streamlit)
  └─ ProcessPoolExecutor
       └─ init_worker_with_dataframe()  ← DataFrame chargé 1x par worker
            └─ run_backtest_worker()     ← Fonction picklable isolée
                 └─ BacktestEngine.run_sweep_iteration()
                      └─ strategy.generate_signals()
```

### Points d'attention

1. **Pickling** : votre classe de stratégie sera instanciée dans chaque worker. Elle ne doit PAS référencer d'objets Streamlit, de connexions DB, ou de ressources non-sérialisables.

2. **Cache d'indicateurs** : le moteur cache les résultats d'indicateurs par `(nom, params_tuple)`. Si vos paramètres d'indicateur ne changent pas entre combos (ex: même `bb_period`), le calcul est réutilisé.

3. **Signaux vectorisés** : privilégiez les opérations NumPy vectorisées. Une boucle `for i in range(n)` dans `generate_signals()` sera appelée des milliers de fois.

4. **Pas de print/logging** : en mode sweep, les logs sont désactivés pour performance.

5. **Pas de modification du DataFrame** : en mode sweep, le DataFrame est partagé entre itérations. Si vous ajoutez des colonnes (ex: `df["bb_stop_long"]`), elles persisteront et pollueront les itérations suivantes. Utilisez des variables locales.

---

## 8. Annotation "Labs"

Pour les stratégies en exploration paramétrique :

- Suffixe `_labs` dans le nom de registre : `"scalp_ema_bb_rsi_labs"`
- Icône `🧪` dans le `ui_label`
- Mention explicite dans la description et la docstring
- Rappelle que les résultats grid search ne sont PAS représentatifs d'un usage réel

---

## 9. Vérification rapide

```bash
python -c "
from strategies import list_strategies
from strategies.base import get_strategy
print('Registry:', list_strategies())
s = get_strategy('ma_strategie')()
print('Name:', s.name)
print('Indicators:', s.required_indicators)
print('Grid params:', list(s.param_ranges.keys()))
"
```

Si le registre ne contient pas votre stratégie, vérifiez que l'import dans `__init__.py` ne lève pas d'erreur silencieuse (exécutez-le isolément).
