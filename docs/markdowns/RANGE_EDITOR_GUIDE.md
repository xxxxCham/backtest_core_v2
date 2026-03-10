# 📝 Guide d'Utilisation - Éditeur de Plages de Paramètres

## 📋 Table des Matières

1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Utilisation](#utilisation)
   - [Interface Streamlit](#interface-streamlit)
   - [CLI (Ligne de commande)](#cli-ligne-de-commande)
   - [Utilisation programmatique](#utilisation-programmatique)
4. [Structure du fichier de configuration](#structure-du-fichier-de-configuration)
5. [Exemples pratiques](#exemples-pratiques)
6. [Sécurité et sauvegardes](#sécurité-et-sauvegardes)
7. [Dépannage](#dépannage)

---

## Introduction

L'**Éditeur de Plages de Paramètres** permet de configurer les valeurs minimales, maximales, les pas et les valeurs par défaut de tous les indicateurs techniques et stratégies du projet.

### Pourquoi ajuster les plages ?

- **Optimisation fine** : Adapter les plages à votre style de trading
- **Performance** : Réduire l'espace de recherche pour des sweeps plus rapides
- **Flexibilité** : Tester des configurations extrêmes ou conservatrices
- **Multi-timeframe** : Ajuster selon le timeframe (1h vs 1d)

---

## Installation

### Prérequis

```powershell
# 1. Installer les dépendances manquantes
pip install tomli tomli-w

# 2. Vérifier l'installation
python -c "import tomli, tomli_w; print('✅ Dépendances OK')"
```

### Structure des fichiers

```
backtest_core/
├── config/
│   ├── indicator_ranges.toml          # Fichier de configuration principal
│   └── indicator_ranges.toml.bak      # Sauvegarde automatique
├── tools/
│   └── edit_ranges.py                 # CLI
├── ui/
│   ├── range_editor.py                # Module UI
│   └── pages/
│       └── range_editor_page.py       # Page Streamlit
├── utils/
│   └── range_manager.py               # Gestionnaire central
└── edit_ranges.bat                    # Launcher Windows
```

---

## Utilisation

### Interface Streamlit

#### Lancement

**Option 1 : Script batch (Windows)**
```powershell
# Double-clic ou:
.\edit_ranges.bat
```

**Option 2 : Commande directe**
```powershell
streamlit run ui\pages\range_editor_page.py --server.port=8502
```

**Option 3 : Depuis l'interface principale**
```powershell
# Ajouter dans la navigation de ui/app.py:
# Page "⚙️ Éditeur de Plages"
```

#### Interface

L'interface Streamlit offre :

1. **Vue d'ensemble** : Statistiques globales (catégories, paramètres, statut)
2. **Recherche** : Filtrer rapidement par nom
3. **Édition visuelle** : Sliders et champs numériques
4. **Validation** : Vérification automatique des contraintes
5. **Sauvegarde** : Backup automatique avant toute modification

![Interface Streamlit](docs/images/range_editor_ui.png)

---

### CLI (Ligne de commande)

Le CLI offre un contrôle précis et peut être automatisé dans des scripts.

#### Commandes disponibles

##### 1. Lister les catégories

```powershell
python tools\edit_ranges.py list
```

**Sortie :**
```
📚 Catégories disponibles:
============================================================
  • ema (4 paramètres)
  • rsi (3 paramètres)
  • bollinger (2 paramètres)
  • macd (3 paramètres)
  ...
```

##### 2. Lister les paramètres d'une catégorie

```powershell
python tools\edit_ranges.py list ema
```

**Sortie :**
```
📋 Paramètres de la catégorie 'ema':
============================================================
  • period
    Min: 5, Max: 200, Step: 1
    Default: 20
    Description: Période EMA

  • short_period
    Min: 5, Max: 30, Step: 1
    Default: 12
    Description: EMA courte
  ...
```

##### 3. Afficher une plage spécifique

```powershell
python tools\edit_ranges.py show ema.period
```

**Sortie :**
```
🔍 Configuration de ema.period:
============================================================
  Min:         5
  Max:         200
  Step:        1
  Default:     20
  Type:        auto
  Description: Période EMA
```

##### 4. Modifier une plage

```powershell
# Modifier min et max
python tools\edit_ranges.py set ema.period --min 3 --max 300

# Modifier uniquement le step
python tools\edit_ranges.py set ema.period --step 2

# Mode dry-run (tester sans sauvegarder)
python tools\edit_ranges.py set ema.period --min 10 --dry-run
```

**Sortie :**
```
✅ Plage 'ema.period' mise à jour avec succès.
📁 Sauvegarde créée: D:\backtest_core\config\indicator_ranges.toml.bak

📊 Nouvelle configuration:
  Min: 3, Max: 300, Step: 1, Default: 20
```

##### 5. Exporter en JSON

```powershell
python tools\edit_ranges.py export ranges_backup.json
```

##### 6. Mode interactif

```powershell
python tools\edit_ranges.py interactive
```

**Session interactive :**
```
🎮 Mode interactif - Éditeur de plages
============================================================
Commandes disponibles:
  list                    - Lister les catégories
  list <category>         - Lister les paramètres d'une catégorie
  show <category.param>   - Afficher une plage
  set <category.param>    - Modifier une plage
  save                    - Sauvegarder les modifications
  exit                    - Quitter

📝 > list ema

📋 Paramètres de 'ema':
  • period [5-200]
  • short_period [5-30]
  • long_period [20-100]

📝 > set ema.period

✏️ Édition de ema.period:
  Valeurs actuelles: Min=5, Max=200, Step=1, Default=20
  (Appuyez sur Entrée pour conserver la valeur actuelle)
  Min [5]: 3
  Max [200]: 250
  Step [1]:
  Default [20]:
✅ Modification appliquée (non sauvegardée).

📝 > save
✅ Modifications sauvegardées.

📝 > exit
👋 Au revoir!
```

---

### Utilisation programmatique

Pour intégrer l'éditeur dans vos scripts Python :

```python
from utils.range_manager import RangeManager, load_indicator_ranges

# 1. Charger le gestionnaire
manager = load_indicator_ranges()

# 2. Lire une plage
ema_period = manager.get_range("ema", "period")
print(f"EMA period: {ema_period.min}-{ema_period.max}, default={ema_period.default}")

# 3. Modifier une plage
manager.update_range("ema", "period", min_val=3, max_val=300)

# 4. Sauvegarder (avec backup automatique)
manager.save_ranges(backup=True)

# 5. Appliquer aux stratégies
from utils.range_manager import apply_ranges_to_strategy

updated_specs = apply_ranges_to_strategy(
    strategy_name="ema_cross",
    parameter_specs=original_specs,
    range_manager=manager
)
```

#### Exemple avancé : Batch update

```python
from utils.range_manager import get_global_range_manager

# Singleton global (pratique pour éviter recharges multiples)
manager = get_global_range_manager()

# Mise à jour batch
updates = [
    ("ema", "period", {"min": 3, "max": 300}),
    ("rsi", "period", {"min": 5, "max": 30}),
    ("bollinger", "std_dev", {"min": 1.0, "max": 4.0}),
]

for category, param, changes in updates:
    manager.update_range(category, param, **changes)
    print(f"✅ {category}.{param} mis à jour")

manager.save_ranges(backup=True)
print("💾 Toutes les modifications sauvegardées")
```

---

## Structure du fichier de configuration

Le fichier `config/indicator_ranges.toml` utilise le format TOML (simple et lisible).

### Format de base

```toml
[category.param]
min = 5
max = 200
step = 1
default = 20
description = "Description du paramètre"
```

### Types supportés

#### 1. Paramètres numériques (entiers)

```toml
[ema.period]
min = 5
max = 200
step = 1
default = 20
description = "Période EMA"
```

#### 2. Paramètres numériques (flottants)

```toml
[bollinger.std_dev]
min = 1.5
max = 3.0
step = 0.1
default = 2.0
description = "Multiplicateur d'écart-type"
```

#### 3. Paramètres à options prédéfinies

```toml
[volume_oscillator.method]
options = ["ema", "sma"]
default = "ema"
description = "MA method"
type = "string"
```

### Catégories disponibles

- **Indicateurs techniques** : `ema`, `sma`, `rsi`, `macd`, `bollinger`, `atr`, `adx`, `stochastic`, etc.
- **Stratégies** : `ema_cross`, `rsi_reversal`, `atr_channel`, etc.
- **Gestion du risque** : `risk` (stop_loss, take_profit, fees, etc.)

---

## Exemples pratiques

### Exemple 1 : Optimiser pour scalping (timeframe court)

```powershell
# EMA plus réactives
python tools\edit_ranges.py set ema.short_period --min 3 --max 15
python tools\edit_ranges.py set ema.long_period --min 10 --max 50

# RSI plus sensible
python tools\edit_ranges.py set rsi.overbought --min 75 --max 85
python tools\edit_ranges.py set rsi.oversold --min 15 --max 25
```

### Exemple 2 : Trading long terme (daily)

```powershell
# EMA plus longues
python tools\edit_ranges.py set ema.short_period --min 20 --max 50
python tools\edit_ranges.py set ema.long_period --min 50 --max 200

# Bollinger plus larges
python tools\edit_ranges.py set bollinger.std_dev --min 2.0 --max 4.0
```

### Exemple 3 : Exploration exhaustive (research)

```powershell
# Élargir toutes les plages RSI
python tools\edit_ranges.py set rsi.period --min 3 --max 50
python tools\edit_ranges.py set rsi.overbought --min 60 --max 90
python tools\edit_ranges.py set rsi.oversold --min 10 --max 40
```

### Exemple 4 : Réduire l'espace de recherche (sweep rapide)

```python
# Script Python pour optimisation rapide
from utils.range_manager import get_global_range_manager

manager = get_global_range_manager()

# Réduire les plages EMA (moins de combinaisons)
manager.update_range("ema", "short_period", min_val=10, max_val=15)
manager.update_range("ema", "long_period", min_val=40, max_val=50)

# Augmenter les steps (moins de valeurs testées)
manager.update_range("rsi", "period", step=2)  # Au lieu de 1
manager.update_range("bollinger", "std_dev", step=0.5)  # Au lieu de 0.1

manager.save_ranges()
```

---

## Sécurité et sauvegardes

### Sauvegarde automatique

À chaque modification via CLI ou UI, un backup est créé :

```
config/indicator_ranges.toml.bak
```

### Restaurer depuis backup

```powershell
# Méthode 1 : Renommer manuellement
move config\indicator_ranges.toml.bak config\indicator_ranges.toml

# Méthode 2 : Via Python
python -c "import shutil; shutil.copy('config/indicator_ranges.toml.bak', 'config/indicator_ranges.toml')"
```

### Versioning Git

```powershell
# Commiter les plages personnalisées
git add config/indicator_ranges.toml
git commit -m "chore: ajuster plages RSI pour trading court terme"

# Revenir à une version précédente
git checkout HEAD~1 -- config/indicator_ranges.toml
```

### Export régulier

```powershell
# Créer un export horodaté
python tools\edit_ranges.py export "backups\ranges_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"

# Ou via batch (Windows)
FOR /F "tokens=1-3 delims=/ " %%A IN ('date /t') DO SET CURRENT_DATE=%%C%%B%%A
python tools\edit_ranges.py export "backups\ranges_%CURRENT_DATE%.json"
```

---

## Dépannage

### Problème : "Fichier de configuration non trouvé"

**Cause** : Le fichier `config/indicator_ranges.toml` est manquant.

**Solution** :
```powershell
# Vérifier l'existence
dir config\indicator_ranges.toml

# Si absent, restaurer depuis backup
move config\indicator_ranges.toml.bak config\indicator_ranges.toml

# Ou recréer depuis le dépôt Git
git checkout config/indicator_ranges.toml
```

### Problème : "Module 'tomli' not found"

**Cause** : Dépendances manquantes.

**Solution** :
```powershell
pip install tomli tomli-w
```

### Problème : "Min doit être < Max"

**Cause** : Validation des contraintes.

**Solution** :
```powershell
# Vérifier les valeurs avant modification
python tools\edit_ranges.py show ema.period

# Utiliser --dry-run pour tester
python tools\edit_ranges.py set ema.period --min 10 --max 5 --dry-run
# Erreur attendue : Min doit être < Max
```

### Problème : Modifications non appliquées aux backtests

**Cause** : Cache ou session Streamlit active.

**Solution** :
```powershell
# 1. Recharger Streamlit (Ctrl+R dans le navigateur)

# 2. Vérifier que le gestionnaire utilise le bon fichier
python -c "from utils.range_manager import get_global_range_manager; mgr = get_global_range_manager(); print(mgr.config_path)"

# 3. Forcer rechargement en redémarrant Streamlit
# Arrêter (Ctrl+C) puis relancer
streamlit run ui\app.py
```

### Problème : "PermissionError: [WinError 32]"

**Cause** : Fichier verrouillé par un autre processus.

**Solution** :
```powershell
# Fermer tous les éditeurs/terminaux ouvrant le fichier
# Puis réessayer

# Si persiste, redémarrer l'explorateur Windows
taskkill /f /im explorer.exe
start explorer.exe
```

---

## 📚 Ressources complémentaires

- **Code source** : `utils/range_manager.py` - Documentation inline complète
- **Tests** : `tests/test_range_manager.py` - Exemples d'utilisation avancés
- **AGENTS.md** : Section "Configurations validées rentables" pour presets testés

---

## 🤝 Contribution

Pour ajouter un nouveau paramètre au système de plages :

1. **Ajouter dans `indicator_ranges.toml`** :
```toml
[ma_nouvelle_categorie.nouveau_param]
min = 10
max = 100
step = 5
default = 50
description = "Description du paramètre"
```

2. **Utiliser dans une stratégie** :
```python
from utils.range_manager import apply_ranges_to_strategy

class MaStrategie(StrategyBase):
    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        # Définir les specs de base
        base_specs = {
            "nouveau_param": ParameterSpec(
                name="nouveau_param",
                min_val=10, max_val=100,  # Valeurs par défaut
                default=50,
                param_type="int",
                description="Mon nouveau paramètre"
            )
        }

        # Appliquer les plages configurables
        return apply_ranges_to_strategy("ma_categorie", base_specs)
```

3. **Tester** :
```powershell
python tools\edit_ranges.py list ma_nouvelle_categorie
python tools\edit_ranges.py show ma_nouvelle_categorie.nouveau_param
```

---

## 📞 Support

En cas de problème non résolu par ce guide :

1. Vérifier `AGENTS.md` - Section "Cahier de Maintenance"
2. Consulter les logs : `logs/backtest_core.log`
3. Créer un ticket avec :
   - Commande exacte exécutée
   - Message d'erreur complet
   - Version Python : `python --version`
   - Contenu de `config/indicator_ranges.toml` (si pertinent)

---

**Version** : 1.0.0
**Dernière mise à jour** : 03/02/2026
**Auteur** : Agent IA - GitHub Copilot
