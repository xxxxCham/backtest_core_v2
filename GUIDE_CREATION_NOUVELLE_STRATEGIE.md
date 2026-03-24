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
        # 54 indicateurs disponibles — voir Section 4 pour la liste complète et les types (dict/array)

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

### Patterns INTERDITS — erreurs SIG001 (Builder et moteur)

Ces constructions provoquent des erreurs runtime dans le moteur et dans le Strategy Builder LLM.
Elles sont détectées et rejetées automatiquement.

| Pattern interdit | Alternative correcte |
|-----------------|---------------------|
| `signals.loc[mask, 'signal'] = 1` | `signals[mask] = 1.0` |
| `signals.notnull()` / `signals.isnull()` | `signals != 0` |
| `for i in range(len(df)): signals[i] = ...` | `signals[long_mask] = 1.0` |
| `mask = close[50:] > ema[50:]` (slice tronqué) | `mask = close > ema` (même longueur) |
| `long_mask = (a > b) and (c > d)` (scalaire) | `long_mask = (a > b) & (c > d)` |
| `signals[long_mask[1:]] = 1` (masque décalé) | `signals[long_mask] = 1.0` |
| `indicators['bollinger_upper']` | `indicators['bollinger']['upper']` |
| `adx_d = indicators['adx']` (nu) | `adx_d = np.nan_to_num(indicators['adx']['adx'])` |
| `crosses_above(x, y)` (pseudo-helper) | Voir section 11 — implémentation numpy |
| `diff = np.diff(close)` (longueur n-1) | `diff = np.insert(np.diff(close), 0, 0.0)` |

> **Règle d'or** : `generate_signals` doit être **100 % vectorisé** et travailler sur des tableaux de longueur `len(df)` du début à la fin.

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

### Noms de paramètres dégénérés (à éviter)

Le Builder LLM peut parfois produire des clés de paramètres très longues ou répétitives du type :
```
distance_to_force_index_weight_volume_weight_volume_...
```
Ces noms sont **filtrés et supprimés** automatiquement par le pipeline Builder avant validation.
Lors d'une écriture manuelle, limitez les clés à une forme courte et descriptive (`atr_period`, `rsi_threshold`, `sl_factor`).

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

### Liste complète des 54 indicateurs disponibles

#### Type ARRAY (accès direct)
Ces indicateurs retournent un `np.ndarray` de longueur `n`.
Accès : `np.nan_to_num(indicators['nom'])`

| Indicateur | Description |
|-----------|-------------|
| `atr` | Average True Range (volatilité) |
| `cci` | Commodity Channel Index |
| `cmo` | Chande Momentum Oscillator |
| `coppock_curve` | Coppock Curve (momentum long terme) |
| `dpo` | Detrended Price Oscillator |
| `ema` | Exponential Moving Average |
| `eom` | Ease of Movement |
| `fear_greed` | Indice Fear & Greed (sentiment) |
| `fisher_transform` | Fisher Transform |
| `force_index` | Force Index (volume × variation) |
| `hma` | Hull Moving Average |
| `kst` | Know Sure Thing oscillator |
| `kvo` | Klinger Volume Oscillator |
| `mass_index` | Mass Index (retournement de tendance) |
| `mfi` | Money Flow Index |
| `momentum` | Momentum brut (n-périodes) |
| `obv` | On-Balance Volume |
| `onchain_smoothing` | Lissage on-chain (crypto) |
| `pi_cycle` | Pi Cycle Top Indicator |
| `roc` | Rate of Change (%) |
| `rsi` | Relative Strength Index |
| `sma` | Simple Moving Average |
| `standard_deviation` | Écart-type glissant |
| `tma` | Triangular Moving Average |
| `tsi` | True Strength Index |
| `ultimate_oscillator` | Ultimate Oscillator |
| `volume_oscillator` | Oscillateur de volume |
| `vwap` | Volume Weighted Average Price |
| `williams_r` | Williams %R |
| `wma` | Weighted Moving Average |
| `amplitude_hunter` | Détecteur d'amplitude de swing |
| `chaikin_oscillator` | Chaikin Money Flow Oscillator |
| `cmf` | Chaikin Money Flow |
| `elder_ray` | Elder Ray Index |

#### Type DICT (accès par sous-clé)
Ces indicateurs retournent un `dict`. **Ne jamais passer le dict brut à `np.nan_to_num()`**.
Syntaxe : `val = np.nan_to_num(indicators['nom']['sous_cle'])`

| Indicateur | Sous-clés disponibles |
|-----------|----------------------|
| `bollinger` | `upper`, `middle`, `lower` |
| `macd` | `macd`, `signal`, `histogram` |
| `stochastic` | `stoch_k`, `stoch_d` |
| `adx` | `adx`, `plus_di`, `minus_di` |
| `supertrend` | `supertrend`, `direction` |
| `ichimoku` | `tenkan`, `kijun`, `senkou_a`, `senkou_b`, `chikou`, `cloud_position` |
| `psar` | `sar`, `trend`, `signal` |
| `vortex` | `vi_plus`, `vi_minus`, `signal`, `oscillator` |
| `stoch_rsi` | `k`, `d`, `signal` |
| `aroon` | `aroon_up`, `aroon_down` |
| `donchian` | `upper`, `middle`, `lower` |
| `keltner` | `upper`, `middle`, `lower` |
| `pivot_points` | `pivot`, `r1`, `s1`, `r2`, `s2`, `r3`, `s3` |
| `fibonacci_levels` | `high`, `low` |
| `fvg` | `fvg_bullish`, `fvg_bearish` |
| `swing` | `swing_high`, `swing_low` |
| `smart_legs` | `smart_leg_bullish`, `smart_leg_bearish` |
| `directional_bias` | `bull_score`, `bear_score`, `net_bias` |
| `markov_switching` | `regime`, `prob_regime_0`, `prob_regime_1`, `prob_regime_2`, `prob_regime_3` |

### Exemples d'accès correct

```python
# Indicateurs array
rsi       = np.nan_to_num(indicators['rsi'])
atr       = np.nan_to_num(indicators['atr'])
ema       = np.nan_to_num(indicators['ema'])
cci       = np.nan_to_num(indicators['cci'])

# Indicateurs dict ─ TOUJOURS extraire la sous-clé d'abord
bb        = indicators['bollinger']
upper     = np.nan_to_num(bb['upper'])
middle    = np.nan_to_num(bb['middle'])
lower     = np.nan_to_num(bb['lower'])

adx_data  = indicators['adx']
adx_val   = np.nan_to_num(adx_data['adx'])
plus_di   = np.nan_to_num(adx_data['plus_di'])
minus_di  = np.nan_to_num(adx_data['minus_di'])

macd_data = indicators['macd']
macd_line = np.nan_to_num(macd_data['macd'])
sig_line  = np.nan_to_num(macd_data['signal'])

st        = indicators['supertrend']
st_val    = np.nan_to_num(st['supertrend'])
st_dir    = np.nan_to_num(st['direction'])   # +1 = uptrend, -1 = downtrend
```

Toujours utiliser `np.nan_to_num()` sur chaque sous-clé **individuellement**, jamais sur le dict entier.

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

```bash
# Vérifier le registre d'indicateurs complet (54 entrées attendues)
python -c "
from indicators.registry import list_indicators, _INDICATOR_REGISTRY
names = list_indicators()
print('Indicateurs:', len(names))
"
```

---

## 10. Indicateurs spécialisés — Filtres et Patterns

Ces indicateurs sont disponibles dans le registre mais leur usage est plus spécifique.
Ils sont conçus pour **filtrer** ou **confirmer**, rarement comme déclencheurs principaux.

### FVG — Fair Value Gaps

```python
fvg      = indicators['fvg']
bullish  = np.nan_to_num(fvg['fvg_bullish']).astype(bool)  # True quand gap haussier détecté
bearish  = np.nan_to_num(fvg['fvg_bearish']).astype(bool)  # True quand gap baissier détecté
```

Usage : confirmer une entrée dans la direction du gap, éviter les entrées contre le gap.

### Swing — Points pivots de swing

```python
sw         = indicators['swing']
swing_hi   = np.nan_to_num(sw['swing_high'])   # prix du dernier swing high
swing_lo   = np.nan_to_num(sw['swing_low'])    # prix du dernier swing low
```

Usage : support/résistance dynamique, confluences de structure de marché.

### Smart Legs — Impulsions intelligentes

```python
sl_data   = indicators['smart_legs']
sl_bull   = np.nan_to_num(sl_data['smart_leg_bullish']).astype(bool)
sl_bear   = np.nan_to_num(sl_data['smart_leg_bearish']).astype(bool)
```

Usage : détecter les impulsions qualitatives, filtrer les signaux en consolidation.

### Directional Bias — Score directionnel

```python
db        = indicators['directional_bias']
bull_sc   = np.nan_to_num(db['bull_score'])  # 0-100 : force haussière
bear_sc   = np.nan_to_num(db['bear_score'])  # 0-100 : force baissière
net_bias  = np.nan_to_num(db['net_bias'])    # bull_score - bear_score
```

Usage : **filtre de contexte**, autoriser les longs seulement si `net_bias > 10`, par exemple.
Pas un signal d'entrée rapide — se comporte comme une confirmation de contexte.

### Markov Switching — Régime de marché

```python
mk        = indicators['markov_switching']
regime    = np.nan_to_num(mk['regime'])            # 0, 1, 2 ou 3 — régime actuel
prob_0    = np.nan_to_num(mk['prob_regime_0'])     # probabilité d'être en régime 0
prob_1    = np.nan_to_num(mk['prob_regime_1'])     # probabilité d'être en régime 1
```

Usage : **gating macro-régime** — ne prendre des positions qu'en régime 0 (trending).
**Ne pas utiliser** comme trigger d'entrée rapide (coûteux, résolution lente).
**Exemple de filtre :**

```python
# Ouvrir longs seulement en régime trending (0 ou 1) avec probabilité élevée
trending_filter = (regime == 0) | ((regime == 1) & (prob_1 > 0.6))
long_mask = long_mask & trending_filter
```

---

## 11. Compatibilité avec le Strategy Builder LLM

Le **Strategy Builder** est le moteur LLM autonome du projet : il génère, teste et itère automatiquement des stratégies en sandbox.
Toute stratégie écrite manuellement doit respecter le même contrat pour être compatible.

### Ce que le Builder génère automatiquement

1. **Une classe `BuilderGeneratedStrategy`** héritant de `StrategyBase`
2. **`required_indicators`** : liste des indicateurs utilisés dans `generate_signals`
3. **`default_params`** et **`parameter_specs`** : paramètres avec bornes pour optimisation
4. **`generate_signals`** : logique vectorisée complète
5. Le fichier est sauvegardé dans `sandbox_strategies/<session_id>/strategy.py`

### Préambule de bindings injecté automatiquement

Le Builder injecte en tête de `generate_signals` un bloc de bindings qui assure que les alias attendus par la logique sont définis :

```python
def generate_signals(self, df, indicators, params):
    # -- Bindings injectés par le Builder --
    close  = np.nan_to_num(df['close'].values)
    high   = np.nan_to_num(df['high'].values)
    low    = np.nan_to_num(df['low'].values)
    volume = np.nan_to_num(df['volume'].values)
    rsi    = np.nan_to_num(indicators['rsi'])
    bb     = indicators['bollinger']
    upper  = np.nan_to_num(bb['upper'])       # alias stable bollinger_upper
    lower  = np.nan_to_num(bb['lower'])       # alias stable bollinger_lower
    # ... puis logique LLM ...
```

### Aliases préférés (alias stables Builder)

Pour maintenir la cohérence entre prompts LLM et codes générés, ces alias sont standardisés :

| Indicateur | Alias court (prompt) | Alias stable (code) |
|-----------|---------------------|--------------------|
| `bollinger` | `upper`, `middle`, `lower` | `bollinger_upper`, `bollinger_lower` |
| `macd` | `macd_line`, `sig_line` | `macd_signal` |
| `supertrend` | `st_val`, `st_dir` | `supertrend_direction` |
| `markov_switching` | `regime`, `prob_0` | `markov_regime` |
| `directional_bias` | `net_bias` | — |

### Implémentation des croisements (cross_up / cross_down)

Le Builder réécrit automatiquement ces pseudo-fonctions en numpy.
Dans du code manuel, utilisez directement :

```python
# Cross up : x passe au-dessus de y
prev_x    = np.roll(x, 1);  prev_x[0]  = np.nan
prev_y    = np.roll(y, 1);  prev_y[0]  = np.nan
cross_up  = (x > y) & (prev_x <= prev_y)
cross_dn  = (x < y) & (prev_x >= prev_y)
```

### Règle de levier

Toujours définir `"leverage": 1` dans `default_params`.
Le moteur utilise `leverage=3` par défaut (aggressif) si le param est absent — cela amplifie les pertes.

### Stops ATR écrits dans le DataFrame

Le simulateur lit automatiquement ces colonnes si elles sont présentes :

```python
# Écrire les niveaux de SL/TP sur les barres d'entrée uniquement
entry_bars = long_mask.nonzero()[0]
for i in entry_bars:
    df.loc[df.index[i], "bb_stop_long"] = df['close'].iloc[i] - stop_mult * atr[i]
    df.loc[df.index[i], "bb_tp_long"]   = df['close'].iloc[i] + tp_mult   * atr[i]

# Version vectorisée (plus rapide)
df.loc[:, "bb_stop_long"] = np.where(long_mask,  close - stop_mult * atr, np.nan)
df.loc[:, "bb_tp_long"]   = np.where(long_mask,  close + tp_mult   * atr, np.nan)
df.loc[:, "bb_stop_short"]= np.where(short_mask, close + stop_mult * atr, np.nan)
df.loc[:, "bb_tp_short"]  = np.where(short_mask, close - tp_mult   * atr, np.nan)
```

### Comment utiliser une stratégie Builder en dehors du sandbox

```python
from strategies.base import register_strategy, StrategyBase

# Copier le fichier sandbox vers strategies/
# Renommer la classe et la clé de registre
# Ajouter l'entrée dans strategies/__init__.py et indicators_mapping.py
```

---

## 12. Nouvelles métriques — Alpha simple

Depuis mars 2026, le moteur calcule un **alpha simple** automatiquement pour chaque backtest.

| Métrique | Formule | Interprétation |
|---------|---------|----------------|
| `benchmark_return_pct` | Return buy & hold sur même période | Référence du marché |
| `alpha_simple_pct` | `total_return - benchmark_return` | Surperformance vs buy & hold |

> Un `+150%` de return avec un `alpha_simple` de `-50%` signifie que le buy & hold aurait fait `+200%` — la stratégie sous-performe le marché même en étant profitable.

Accès en Python :

```python
result = engine.run(df=data, params=params)
print(result.metrics['total_return_pct'])     # return stratégie
print(result.metrics['benchmark_return_pct']) # buy & hold
print(result.metrics['alpha_simple_pct'])     # alpha = sur/sous-performance
```

Ces métriques sont disponibles dans :
- L'UI Streamlit (carte et graphique equity)
- Les résultats de sweep/grid
- Le hub de résultats (colonnes `metrics_benchmark_return_pct`, `metrics_alpha_simple_pct`)
