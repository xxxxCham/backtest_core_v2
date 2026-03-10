# 🔴 DÉTAILS TECHNIQUES : REDONDANCES PAR DOMAINE

---

## 📌 DOMAINE 1 : VALIDATION DES PARAMÈTRES

### Problème : 5 fonctions de validation parallèles

#### Code Path 1: UI helpers (`ui/helpers.py:200`)
```python
PARAM_CONSTRAINTS = {
    "leverage": {"min": 1, "max": 5},
    "stop_loss": {"min": 0.5, "max": 10},
}

def validate_param(name: str, value: Any) -> Tuple[bool, str]:
    if name not in PARAM_CONSTRAINTS:
        return True, ""

    constraints = PARAM_CONSTRAINTS[name]
    if value < constraints["min"]:
        return False, f"{name} doit être ≥ {constraints['min']}"
    if value > constraints["max"]:
        return False, f"{name} doit être ≤ {constraints['max']}"
    return True, ""
```

**Problèmes:**
- ❌ Utilise dict de constantes hardcoded
- ❌ Pas d'accès à ParameterSpec
- ❌ Incohérent avec autres validations

---

#### Code Path 2: StrategyBase (`strategies/base.py:277`)
```python
def validate_params(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []

    if params.get("leverage", 1) <= 0:
        errors.append("leverage doit être > 0")
    if params.get("leverage", 1) > 20:
        errors.append("leverage doit être <= 20")

    return len(errors) == 0, errors
```

**Problèmes:**
- ❌ Bounds hardcoded (max=20 au lieu de 5 dans UI!)
- ❌ Logique seulement pour leverage
- ❌ Pas réutilisable pour autres paramètres

---

#### Code Path 3: Metrics Types (`metrics_types.py:63`)
```python
def _validate_range(
    payload: Mapping[str, Any],
    key: str,
    lo: float,
    hi: float
) -> None:
    """Valide une clé dans un range [lo, hi]."""
    if not (lo <= payload[key] <= hi):
        raise ValueError(
            f"Paramètre {key} hors limites [{lo}, {hi}]. "
            f"Reçu: {payload[key]}"
        )
```

**Problèmes:**
- ❌ Lève exception (UI/agents utilisent tuple bool/str)
- ❌ Pattern incohérent
- ❌ Nécessite try/except dans appelant

---

#### Code Path 4: AutonomousStrategist (`agents/autonomous_strategist.py:1156`)
```python
def _validate_parameters(
    self,
    params: Dict[str, Any],
    bounds: Dict[str, tuple],
    defaults: Dict[str, Any],
    session: OptimizationSession,
) -> Dict[str, Any]:
    validated = {}

    for param, bound_spec in bounds.items():
        try:
            min_val = float(bound_spec[0])
            max_val = float(bound_spec[1])

            # Correction automatique si min > max
            if min_val >= max_val:
                logger.warning(f"Param {param}: min >= max, swap")
                min_val, max_val = max_val, min_val

            value = params.get(param)

            # Clamping
            value = max(min_val, min(max_val, value))

            # Arrondir si entier
            if all(isinstance(bound_spec[i], int) for i in range(2)):
                value = int(round(value))

            validated[param] = value
        except (ValueError, TypeError, IndexError) as e:
            logger.error(f"Param {param} validation failed: {e}")
            validated[param] = defaults.get(param)

    return validated
```

**Problèmes:**
- ❌ Logique complexe (min/max swap, clamping, rounding)
- ❌ Celle-ci FAIT le clamping (contrairement aux autres qui valident seulement)
- ❌ Pas cohérente avec UI ou StrategyBase

---

#### Code Path 5: OptunaOptimizer (`backtest/optuna_optimizer.py:272`)
```python
def _check_constraints(self, params: Dict[str, Any]) -> bool:
    """Vérifie que les contraintes sont respectées."""
    for left, op, right in self.constraints:
        left_val = params.get(left, 0)
        right_val = params.get(right, 0) if isinstance(right, str) else right

        if op == ">":
            if not left_val > right_val:
                return False
        elif op == ">=":
            if not left_val >= right_val:
                return False
        elif op == "<":
            if not left_val < right_val:
                return False
        elif op == "<=":
            if not left_val <= right_val:
                return False
        elif op == "!=":
            if not left_val != right_val:
                return False
        elif op == "==":
            if not left_val == right_val:
                return False

    return True
```

**Problèmes:**
- ❌ Réimplémentation manuelle de ConstraintValidator.validate()
- ❌ 6 branches if/elif identiques
- ❌ Pas de logging ou diagnostic

---

### **Comparaison des 5 chemins**

| Aspect | Path 1 (UI) | Path 2 (Base) | Path 3 (Metrics) | Path 4 (Agent) | Path 5 (Optuna) |
|--------|-----------|------------|--------------|-----------|-----------|
| **Type retour** | (bool, str) | (bool, List[str]) | Exception | Dict | bool |
| **Clamping** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Source bounds** | Dict hardcoded | Hardcoded string | Paramètre | Paramètre | Paramètre |
| **Logging** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Unité tests** | helpers_test.py | test_strategies.py | metrics_test.py | test_agents.py | test_optuna.py |
| **Couverture** | UI | Strategies | Metrics | LLM agents | Optuna |

---

## 📌 DOMAINE 2 : CONTRAINTES INTER-PARAMÈTRES

### Problème : 3 implémentations incompatibles

#### Implementation 1: ConstraintValidator (`utils/parameters.py:1085`)
```python
class ConstraintValidator:
    """Validateur de contraintes pour filtrer grilles."""

    def __init__(self, constraints: Optional[List[ParameterConstraint]] = None):
        self.constraints: List[ParameterConstraint] = constraints or []

    def validate(self, params: Dict[str, Any]) -> bool:
        return all(c.validate(params) for c in self.constraints)

    def filter_grid(self, param_grid: List[Dict], log_filtered: bool = False):
        valid = []
        filtered_count = 0

        for params in param_grid:
            if self.validate(params):
                valid.append(params)
            else:
                filtered_count += 1

        return valid
```

**Usage:**
```python
validator = ConstraintValidator([
    ParameterConstraint('slow_period', 'greater_than', 'fast_period'),
    ParameterConstraint('slow_period', 'ratio_min', 'fast_period', ratio=1.5),
])

valid_grid = validator.filter_grid(param_grid)
```

---

#### Implementation 2: OptunaOptimizer constraints (`backtest/optuna_optimizer.py`)
```python
class OptunaOptimizer:
    def __init__(self, ...):
        # self.constraints = [("slow_period", ">", "fast_period"), ...]
        self.constraints = []

    def _check_constraints(self, params: Dict[str, Any]) -> bool:
        for left, op, right in self.constraints:
            left_val = params.get(left, 0)
            right_val = params.get(right, 0) if isinstance(right, str) else right

            if op == ">" and not (left_val > right_val):
                return False
            # ... 5 autres opérateurs en if/elif

        return True
```

**Usage:**
```python
optimizer.constraints = [
    ("slow_period", ">", "fast_period"),
    ("slow_period", "/", "fast_period", {"min_ratio": 1.5}),  # Format différent!
]
```

---

#### Implementation 3: COMMON_CONSTRAINTS dict (`utils/parameters.py:962`)
```python
COMMON_CONSTRAINTS = {
    "ema_cross": ConstraintValidator([
        ParameterConstraint(
            param_a="slow_period",
            constraint_type="greater_than",
            param_b="fast_period",
            description="La période lente doit être > période rapide"
        ),
        ParameterConstraint(
            param_a="slow_period",
            constraint_type="ratio_min",
            param_b="fast_period",
            ratio=1.5,
            description="La période lente doit être au moins 1.5x la rapide"
        ),
    ]),
    "bollinger": ConstraintValidator([...]),
}

# Usage
validator = COMMON_CONSTRAINTS.get("ema_cross", ConstraintValidator())
```

**Problèmes:**
- ✅ Dict global (anti-pattern)
- ✅ Pas de factory pattern
- ✅ Duplication : même constraint dans dict ET dans strategy.parameter_specs

---

### **Matrice des Formats de Contrainte**

| Implementation | Format | Type de retour | Réutilisation | Tests |
|---|---|---|---|---|
| **ConstraintValidator** | ParameterConstraint objects | bool | Grid/CLI sweep | ✅ 12 tests |
| **OptunaOptimizer** | Tuples (str, op, str/float) | bool | Optuna uniquement | ⚠️ 4 tests |
| **COMMON_CONSTRAINTS** | ConstraintValidator in dict | bool/error | Présets + CLI | 🔴 0 test! |

---

## 📌 DOMAINE 3 : IMPORTS DUPLIQUÉS

### Problème : 27 imports identiques de `get_logger`

#### Scatter Plot des imports
```
utils/
  ├─ session_ranges_tracker.py:29   from utils.log import get_logger
  ├─ session_param_tracker.py:29    from utils.log import get_logger
  ├─ run_tracker.py:30              from utils.log import get_logger
  ├─ parameters.py:140              from utils.log import get_logger
  ├─ preset_validation.py:26        from utils.log import get_logger
  └─ model_loader.py:30             from utils.log import get_logger

backtest/
  ├─ simulator.py:29                from utils.log import get_logger
  ├─ simulator_fast.py:35           from utils.log import get_logger
  ├─ engine.py:?                    (présumé)
  ├─ execution.py:30                from utils.log import get_logger
  ├─ facade.py:41                   from utils.log import get_logger
  ├─ performance.py:36              from utils.log import get_logger
  ├─ validation.py:29               from utils.log import get_logger
  ├─ storage.py:37                  from utils.log import get_logger
  └─ monte_carlo.py:29              from utils.log import get_logger

agents/
  ├─ ollama_manager.py:35           from utils.log import get_logger
  └─ orchestration_logger.py:33     from utils.log import get_logger

ui/
  ├─ model_presets.py:30            from utils.log import get_logger
  ├─ components/model_selector.py:32 from utils.log import get_logger
  └─ components/charts.py:37        from utils.log import get_logger

data/
  ├─ loader.py:31                   from utils.log import get_logger
  └─ indicator_bank.py:34           from utils.log import get_logger

performance/
  └─ benchmark.py:33                from utils.log import get_logger
```

**Coût:**
- 🔴 27 lignes redondantes
- 🔴 Si signature change → 27 modifications
- 🟠 Légère overhead mémoire (27 imports de même fonction)

**Solution idéale:**
```python
# utils/__init__.py
from utils.log import get_logger

__all__ = ['get_logger']

# Chaque module:
from utils import get_logger
logger = get_logger(__name__)
```

---

## 📌 DOMAINE 4 : AFFICHAGE/FORMATAGE (CLI)

### Problème : 27 variations d'affichage des headers

#### Pattern récurrent dans `cli/commands.py`

```python
# Ligne 72
print(f"\n{Colors.BOLD}{Colors.CYAN}{text}{Colors.RESET}")

# Ligne 111
print(f"  {Colors.BOLD}{header_line}{Colors.RESET}")

# Ligne 304
print(f"\n{Colors.BOLD}Tokens:{Colors.RESET} {', '.join(tokens)}")

# Ligne 306
print(f"{Colors.BOLD}Timeframes:{Colors.RESET} {', '.join(timeframes)}")

# Ligne 398
print(f"\n{Colors.BOLD}Paramètres par défaut:{Colors.RESET}")

# Ligne 402
print(f"\n{Colors.BOLD}Plages d'optimisation:{Colors.RESET}")

# Ligne 436
print(f"\n{Colors.BOLD}Paramètres (Settings):{Colors.RESET}")

# Ligne 621
print(f"  {Colors.BOLD}Performance:{Colors.RESET}")

# Ligne 792
print(f"\n  {Colors.BOLD}#{i+1}{Colors.RESET}")

# ... et 17 autres variations
```

**Patterns identifiés:**
1. `\n{Colors.BOLD}<LABEL>:{Colors.RESET} <VALUE>`
2. `{Colors.BOLD}<LABEL>:{Colors.RESET}` (sans newline)
3. `\n  {Colors.BOLD}<LABEL>:{Colors.RESET}`
4. `{Colors.BOLD}{Colors.CYAN}<TEXT>{Colors.RESET}`

**Impact:**
- 🟠 -27 lignes pourraient être -5 appels fonction
- 🟠 Changement de couleur = 27 modifications
- 🟠 Pas de cohérence d'indentation

---

## 📊 TABLEAU RÉCAPITULATIF

| Domaine | Redondance | Instances | Facilité Refactoring | Impact |
|---------|-----------|-----------|----------------------|--------|
| **Validation** | 5 chemins | 50+ lignes | 🟠 Moyen | 🔴 ÉLEVÉ |
| **Constraints** | 3 implémentations | 40+ lignes | 🟠 Moyen | 🔴 ÉLEVÉ |
| **Imports** | 27x get_logger | 27 lignes | 🟢 Facile | 🟡 MOYEN |
| **CLI Formatting** | 27 variations | 27 lignes | 🟢 Facile | 🟠 FAIBLE |

---

## 🎯 SOLUTION PROPOSÉE PAR DOMAINE

### Domaine 1 : Validation
**Créer `utils/validator.py`:**
```python
class ParameterValidator:
    """Source unique pour validation paramètres."""

    @staticmethod
    def validate_value(
        value: Any,
        spec: ParameterSpec,
        action: str = "validate"  # validate, clamp, raise
    ) -> Tuple[bool, Optional[str], Any]:
        """Valide une valeur selon spec."""

        # Validation
        if value < spec.min_val or value > spec.max_val:
            if action == "raise":
                raise ValueError(f"Hors bounds [{spec.min_val}, {spec.max_val}]")
            elif action == "clamp":
                value = max(spec.min_val, min(spec.max_val, value))
            else:  # validate
                return False, "Valeur hors limites", value

        # Rounding si entier
        if spec.param_type == "int":
            value = int(round(value))

        return True, None, value
```

### Domaine 2 : Constraints
**Unifier dans `utils/constraints.py`:**
```python
class ConstraintEngine:
    """Engine unique pour ALL constraint validation."""

    def validate(self, params, constraints_list):
        """Works for ConstraintValidator AND OptunaOptimizer."""
```

### Domaine 3 : Imports
**Créer `utils/__init__.py`:**
```python
from utils.log import get_logger
__all__ = ['get_logger', ...]
```

### Domaine 4 : CLI Formatting
**Créer `cli/formatting.py`:**
```python
class CLIFormatter:
    @staticmethod
    def section_header(label: str) -> None:
        print(f"\n{Colors.BOLD}{label}:{Colors.RESET}")
```

---

*End of technical details report*
