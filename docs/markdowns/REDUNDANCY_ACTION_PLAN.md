# ✅ PLAN D'ACTION POUR ÉLIMINER LES REDONDANCES

**Date:** 4 janvier 2026
**Durée estimée:** 10-15 jours (1-2 sprints)
**Priorité:** HAUTE (économie maintenance +40%)

---

## 🗓️ FEUILLE DE ROUTE

### **PHASE 1: CRITIQUE (Jours 1-3) — 2 tâches**

#### 1.1️⃣ UNIFIER LES IMPORTS (1 jour, Facile)
**Objectif:** Centraliser `get_logger` dans `utils/__init__.py`

**Fichiers à créer:**
```
utils/__init__.py  (NOUVEAU)
```

**Fichiers à modifier:** 27 fichiers (bulk replace)

**Code:**
```python
# utils/__init__.py (NOUVEAU)
"""
Utilitaires centralisés pour backtest_core.
"""

from utils.log import get_logger

__all__ = [
    'get_logger',
]
```

**Refactoring (27 fichiers):**
```python
# AVANT:
from utils.log import get_logger

# APRÈS:
from utils import get_logger
```

**Validation:**
```bash
# Vérifier aucun import cassé
python -c "from utils import get_logger; print('✅ OK')"
pytest tests/ -k "import" --tb=short
```

**Gain:** -27 lignes, +1 point d'entrée, +20% maintenabilité

---

#### 1.2️⃣ CRÉER PARAMETRVALIDATOR CENTRALISÉ (2 jours, Moyen)
**Objectif:** Remplacer 5 chemins de validation par 1

**Fichier à créer:**
```
utils/validator.py  (NOUVEAU, ~150 lignes)
```

**Code complet:**
```python
# utils/validator.py

from typing import Any, Dict, Tuple, Optional, Union
from dataclasses import dataclass
from utils.log import get_logger
from utils.parameters import ParameterSpec

logger = get_logger(__name__)


class ValidationError(Exception):
    """Exception levée lors d'erreur de validation."""
    pass


class ParameterValidator:
    """
    Source unique pour validation paramètres.

    Remplace:
    - ui/helpers.py:validate_param()
    - strategies/base.py:validate_params()
    - metrics_types.py:_validate_range()
    - agents/autonomous_strategist.py:_validate_parameters()
    """

    @staticmethod
    def validate_value(
        param_name: str,
        value: Any,
        spec: ParameterSpec,
        action: str = "validate"  # "validate", "clamp", "raise"
    ) -> Tuple[bool, Optional[str], Any]:
        """
        Valide une valeur contre une spécification paramètre.

        Args:
            param_name: Nom du paramètre (pour logs)
            value: Valeur à valider
            spec: ParameterSpec avec bounds
            action: "validate" (retour bool), "clamp" (retour valeur corrigée),
                   "raise" (lève exception)

        Returns:
            (is_valid: bool, error_msg: Optional[str], final_value: Any)
        """
        try:
            value_float = float(value)
        except (ValueError, TypeError):
            msg = f"Paramètre '{param_name}': valeur non numérique ({value})"
            if action == "raise":
                raise ValidationError(msg)
            return False, msg, value

        # Vérifier bounds
        if value_float < spec.min_val or value_float > spec.max_val:
            if action == "raise":
                msg = (f"Paramètre '{param_name}': {value} hors limites "
                       f"[{spec.min_val}, {spec.max_val}]")
                raise ValidationError(msg)

            elif action == "clamp":
                # Clamp à l'intérieur des limites
                clamped = max(spec.min_val, min(spec.max_val, value_float))

                # Arrondir si entier
                if spec.param_type == "int":
                    clamped = int(round(clamped))

                msg = f"Paramètre '{param_name}': clampé de {value} à {clamped}"
                logger.debug(msg)
                return True, None, clamped

            else:  # action == "validate"
                msg = (f"Paramètre '{param_name}': {value} hors limites "
                       f"[{spec.min_val}, {spec.max_val}]")
                return False, msg, value

        # Valeur OK, arrondir si nécessaire
        if spec.param_type == "int":
            value_float = int(round(value_float))

        return True, None, value_float

    @staticmethod
    def validate_params(
        params: Dict[str, Any],
        param_specs: Dict[str, ParameterSpec],
        action: str = "validate"  # "validate", "clamp"
    ) -> Tuple[bool, Dict[str, Any], List[str]]:
        """
        Valide TOUS les paramètres.

        Args:
            params: Dict des paramètres
            param_specs: Dict des spécifications (ParameterSpec)
            action: "validate" ou "clamp"

        Returns:
            (all_valid: bool, corrected_params: Dict, errors: List[str])
        """
        errors = []
        corrected = {}

        for param_name, value in params.items():
            if param_name not in param_specs:
                # Paramètre inconnu
                logger.warning(f"Paramètre inconnu: {param_name}")
                corrected[param_name] = value
                continue

            spec = param_specs[param_name]
            is_valid, error_msg, final_value = ParameterValidator.validate_value(
                param_name, value, spec, action=action
            )

            if not is_valid:
                errors.append(error_msg)
                if action == "clamp":
                    corrected[param_name] = final_value
            else:
                corrected[param_name] = final_value

        return len(errors) == 0, corrected, errors

    @staticmethod
    def validate_bounds(min_val: float, max_val: float) -> Tuple[bool, Optional[str]]:
        """Valide que min_val <= max_val."""
        if min_val > max_val:
            return False, f"min_val ({min_val}) > max_val ({max_val})"
        return True, None

    @staticmethod
    def clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp une valeur entre min et max."""
        return max(min_val, min(max_val, value))


class ConstraintValidator:
    """Valide les contraintes inter-paramètres."""

    @staticmethod
    def validate(
        params: Dict[str, Any],
        constraints: List[Dict[str, Any]]
    ) -> Tuple[bool, List[str]]:
        """
        Valide les contraintes inter-paramètres.

        Formats supportés:
        - {"param_a": "slow_period", "op": ">", "param_b": "fast_period"}
        - ParameterConstraint objects
        """
        errors = []

        for constraint in constraints:
            param_a = constraint.get("param_a")
            op = constraint.get("op", constraint.get("constraint_type"))
            param_b = constraint.get("param_b")
            value = constraint.get("value")
            ratio = constraint.get("ratio")

            val_a = params.get(param_a)
            if val_a is None:
                continue  # Paramètre absent, skip

            # Vérifier la contrainte
            if op == "greater_than" and not (val_a > params.get(param_b, val_a)):
                errors.append(f"{param_a} doit être > {param_b}")

            elif op == "ratio_min":
                val_b = params.get(param_b, 1)
                if val_b != 0 and not (val_a / val_b >= (ratio or 1.0)):
                    errors.append(f"{param_a}/{param_b} doit être >= {ratio}")

            # ... ajouter autres opérateurs selon besoin

        return len(errors) == 0, errors
```

**Remplacer:**
- ❌ `ui/helpers.py:validate_param()`
- ❌ `ui/helpers.py:validate_all_params()`
- ❌ `strategies/base.py:validate_params()`
- ❌ `metrics_types.py:_validate_range()`
- ❌ `agents/autonomous_strategist.py:_validate_parameters()` (partiellement)

**Gain:** -100+ lignes, +1 source de vérité, unified exception handling

---

### **PHASE 2: MOYEN (Jours 4-8) — 3 tâches**

#### 2.1️⃣ UNIFIER CONSTRAINTVALIDATOR ET OPTUNAOPTIMIZER (2 jours, Moyen)
**Objectif:** 1 engine pour ALL constraint validation

**Fichier à modifier:**
```
utils/parameters.py  (existing ConstraintValidator)
backtest/optuna_optimizer.py  (refactorer)
```

**Changement:**
```python
# OptunaOptimizer AVANT:
self.constraints = [("slow", ">", "fast"), ...]
def _check_constraints(self, params):
    for left, op, right in self.constraints:
        # ... 6 branches if/elif ...

# OptunaOptimizer APRÈS:
from utils.parameters import ConstraintValidator
self.constraint_validator = ConstraintValidator([...])
def _check_constraints(self, params):
    return self.constraint_validator.validate(params)
```

**Gain:** -50+ lignes OptunaOptimizer, +cohérence

---

#### 2.2️⃣ CLI FORMATTER HELPERS (1 jour, Facile)
**Fichier à créer:**
```
cli/formatting.py  (NOUVEAU, ~80 lignes)
```

**Code:**
```python
# cli/formatting.py

from typing import List, Optional
from utils.colors import Colors


class CLIFormatter:
    """Helpers centralisés pour affichage CLI."""

    @staticmethod
    def section_header(label: str, color: str = Colors.CYAN) -> None:
        """Header de section avec couleur."""
        print(f"\n{Colors.BOLD}{color}{label}:{Colors.RESET}")

    @staticmethod
    def subsection_header(label: str) -> None:
        """Header de sous-section (indenté)."""
        print(f"  {Colors.BOLD}{label}:{Colors.RESET}")

    @staticmethod
    def key_value(label: str, value: str, indent: int = 0) -> None:
        """Affiche clé: valeur."""
        prefix = "  " * indent if indent > 0 else ""
        print(f"{prefix}{Colors.BOLD}{label}:{Colors.RESET} {value}")

    @staticmethod
    def item_number(number: int, indent: int = 1) -> str:
        """Retourne format #{number}."""
        prefix = "  " * indent if indent > 0 else ""
        return f"{prefix}{Colors.BOLD}#{number}{Colors.RESET}"

    @staticmethod
    def list_items(label: str, items: List[str], sep: str = ", ") -> None:
        """Affiche liste d'items."""
        print(f"\n{Colors.BOLD}{label}:{Colors.RESET} {sep.join(items)}")

    @staticmethod
    def error(message: str) -> None:
        """Affiche message d'erreur."""
        print(f"\n{Colors.BOLD}{Colors.RED}❌ {message}{Colors.RESET}")

    @staticmethod
    def success(message: str) -> None:
        """Affiche message de succès."""
        print(f"\n{Colors.BOLD}{Colors.GREEN}✅ {message}{Colors.RESET}")
```

**Usage avant:**
```python
print(f"\n{Colors.BOLD}Paramètres:{Colors.RESET} {', '.join(params)}")
```

**Usage après:**
```python
from cli.formatting import CLIFormatter
CLIFormatter.list_items("Paramètres", params)
```

**Gain:** -27 lignes, +cohérence affichage

---

#### 2.3️⃣ METTRE À JOUR UTILS/__INIT__.PY (0.5 jours, Trivial)
```python
# utils/__init__.py

from utils.log import get_logger
from utils.validator import ParameterValidator, ConstraintValidator
from utils.parameters import ParameterSpec, Preset

__all__ = [
    'get_logger',
    'ParameterValidator',
    'ConstraintValidator',
    'ParameterSpec',
    'Preset',
]
```

---

### **PHASE 3: SUIVI & TESTS (Jours 9-10) — 1 tâche**

#### 3.1️⃣ CONSOLIDATION TESTS (1 jour, Moyen)
**Créer fichiers tests centralisés:**
```
tests/test_validation_unified.py  (NOUVEAU)
tests/test_constraints_unified.py  (NOUVEAU)
tests/test_cli_formatting.py  (NOUVEAU)
```

**Supprimer/consolider:**
- ❌ Duplications dans test_helpers.py
- ❌ Duplications dans test_strategies.py
- ❌ Duplications dans test_agents.py

---

## 📋 CHECKLIST REFACTORING

### Phase 1
- [ ] Créer `utils/__init__.py`
- [ ] Remplacer 27 imports (bulk find-replace)
- [ ] Créer `utils/validator.py`
- [ ] Tests pass: `pytest tests/ -k "validator"` ✅
- [ ] Remplacer `ui/helpers.py:validate_param()` par ParameterValidator
- [ ] Remplacer `strategies/base.py:validate_params()` par ParameterValidator
- [ ] Remplacer `metrics_types.py:_validate_range()` par ParameterValidator
- [ ] Tests pass: `pytest tests/test_validation_unified.py` ✅

### Phase 2
- [ ] Refactorer `backtest/optuna_optimizer.py` → utiliser ConstraintValidator
- [ ] Créer `cli/formatting.py`
- [ ] Refactorer `cli/commands.py` (27 print statements)
- [ ] Tests pass: `pytest tests/test_cli_formatting.py` ✅
- [ ] Mettre à jour `utils/__init__.py` avec exports

### Phase 3
- [ ] Créer `tests/test_validation_unified.py`
- [ ] Créer `tests/test_constraints_unified.py`
- [ ] Créer `tests/test_cli_formatting.py`
- [ ] Lancer full test suite: `pytest tests/` ✅
- [ ] Vérifier coverage >= 85%

---

## 🎯 ESTIMATION EFFORT

| Phase | Tâche | Durée | Difficulté | Priorité |
|-------|-------|-------|-----------|----------|
| **1** | Unifier imports | 1h | 🟢 Facile | 🔴 HAUTE |
| **1** | Validator centralisé | 4h | 🟡 Moyen | 🔴 HAUTE |
| **2** | Unifier Constraints | 4h | 🟡 Moyen | 🟡 MOYEN |
| **2** | CLI Formatter | 2h | 🟢 Facile | 🟠 FAIBLE |
| **3** | Tests consolidation | 4h | 🟡 Moyen | 🟡 MOYEN |
| | **TOTAL** | **15h** | | |

**Pour 1 dev full-time:** 2 jours de sprint
**Pour 1 dev part-time:** 1-2 semaines

---

## 💰 ROI (RETURN ON INVESTMENT)

### Coûts
- **Effort:** 15 heures (~1-2 jours sprint)
- **Risk:** Medium (breaking changes dans imports + validation)

### Bénéfices
- **Maintenabilité:** +40% (une source de vérité au lieu de 5)
- **Testabilité:** +30% (tests centralisés)
- **Temps debug:** -25% (cohérence + logging)
- **Économies annuelles:** ~300+ heures (moins de bugs liés à validation)

**Payback period:** < 1 mois

---

## ⚠️ RISQUES & MITIGATION

| Risque | Impact | Mitigation |
|--------|--------|-----------|
| Breaking changes imports | 🟠 Medium | Feature branch + full test suite before merge |
| Dépendances circulaires | 🔴 High | Audit imports, créer separate module utils/validation.py |
| Performance (overhead validation) | 🟢 Low | Benchmark before/after |
| Adoption par devs | 🟠 Medium | Documentation + exemples |

---

## 📚 DOCUMENTATION À CRÉER

Après refactoring, créer:
```
docs/VALIDATION_GUIDE.md
  ├─ Utiliser ParameterValidator
  ├─ Ajouter contraintes
  └─ Exemples

docs/CONSTRAINTS_REFERENCE.md
  ├─ Types de contraintes supportées
  └─ Exemples multi-domaines

docs/CLI_FORMATTING_GUIDE.md
  ├─ APIFormatter
  └─ Exemples d'utilisation
```

---

**Status:** ✅ Prêt pour planification
**Next:** Assigner tâches, créer branches feature, lancer Phase 1

