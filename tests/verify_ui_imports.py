"""Script de vérification des imports pour l'UI Streamlit.
Vérifie que tous les imports critiques fonctionnent.
"""

import importlib
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

print("=" * 70)
print("VÉRIFICATION DES IMPORTS UI")
print("=" * 70)

# Test 1: Import depuis strategies.indicators_mapping
print("\n1️⃣  Test: strategies.indicators_mapping")
try:
    mapping_module = importlib.import_module("strategies.indicators_mapping")
    strategy_indicators_map = mapping_module.STRATEGY_INDICATORS_MAP
    get_ui_indicators = mapping_module.get_ui_indicators
    print(f"   ✅ STRATEGY_INDICATORS_MAP: {len(strategy_indicators_map)} stratégies")
    print(f"   ✅ get_ui_indicators: {callable(get_ui_indicators)}")

    # Test de la fonction
    test_indicators = get_ui_indicators("bollinger_atr")
    print(f"   ✅ get_ui_indicators('bollinger_atr'): {test_indicators}")
except ImportError as e:
    print(f"   ❌ ERREUR: {e}")
    sys.exit(1)

# Test 2: Import ui.constants
print("\n2️⃣  Test: ui.constants")
try:
    constants_module = importlib.import_module("ui.constants")
    param_constraints = constants_module.PARAM_CONSTRAINTS
    print(f"   ✅ PARAM_CONSTRAINTS: {len(param_constraints)} paramètres")
except ImportError as e:
    print(f"   ❌ ERREUR: {e}")
    sys.exit(1)

# Test 3: Import ui.context
print("\n3️⃣  Test: ui.context")
try:
    context_module = importlib.import_module("ui.context")
    backend_available = context_module.BACKEND_AVAILABLE
    llm_available = context_module.LLM_AVAILABLE
    print(f"   ✅ BACKEND_AVAILABLE: {backend_available}")
    print(f"   ✅ LLM_AVAILABLE: {llm_available}")
except ImportError as e:
    print(f"   ❌ ERREUR: {e}")
    sys.exit(1)

# Test 4: Import ui.main
print("\n4️⃣  Test: ui.main")
try:
    main_module = importlib.import_module("ui.main")
    render_controls = main_module.render_controls
    render_main = main_module.render_main
    render_setup_previews = main_module.render_setup_previews
    print(f"   ✅ render_controls: {callable(render_controls)}")
    print(f"   ✅ render_main: {callable(render_main)}")
    print(f"   ✅ render_setup_previews: {callable(render_setup_previews)}")
except ImportError as e:
    print(f"   ❌ ERREUR: {e}")
    sys.exit(1)

# Test 5: Import ui.sidebar
print("\n5️⃣  Test: ui.sidebar")
try:
    sidebar_module = importlib.import_module("ui.sidebar")
    render_sidebar = sidebar_module.render_sidebar
    print(f"   ✅ render_sidebar: {callable(render_sidebar)}")
except ImportError as e:
    print(f"   ❌ ERREUR: {e}")
    sys.exit(1)

# Test 6: Import ui.results
print("\n6️⃣  Test: ui.results")
try:
    results_module = importlib.import_module("ui.results")
    render_results = results_module.render_results
    print(f"   ✅ render_results: {callable(render_results)}")
except ImportError as e:
    print(f"   ❌ ERREUR: {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ TOUS LES IMPORTS FONCTIONNENT CORRECTEMENT!")
print("=" * 70)
print("\n💡 Si Streamlit affiche toujours une erreur:")
print("   1. Nettoyer le cache: streamlit cache clear")
print("   2. Redémarrer Streamlit: streamlit run ui/app.py")
print("   3. Dans le navigateur: Appuyer sur 'C' puis 'R'\n")
