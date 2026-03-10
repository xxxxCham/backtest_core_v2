# 🎛️ Éditeur de Plages - Quick Start

## Installation Express

```powershell
# 1. Installer les dépendances
pip install tomli tomli-w

# 2. Vérifier l'installation
python -c "import tomli, tomli_w; print('✅ OK')"
```

## 🚀 Utilisation Rapide

### Option 1 : Interface Graphique (Recommandé)

```powershell
# Lancer l'éditeur visuel
.\edit_ranges.bat

# Ou directement :
streamlit run ui\pages\range_editor_page.py --server.port=8502
```

→ Ouvrir http://localhost:8502

### Option 2 : Ligne de Commande

```powershell
# Lister toutes les catégories
python tools\edit_ranges.py list

# Voir les paramètres EMA
python tools\edit_ranges.py list ema

# Afficher une plage spécifique
python tools\edit_ranges.py show ema.period

# Modifier une plage
python tools\edit_ranges.py set ema.period --min 3 --max 300

# Mode interactif
python tools\edit_ranges.py interactive
```

### Option 3 : Code Python

```python
from utils.range_manager import get_global_range_manager

# Charger le gestionnaire
manager = get_global_range_manager()

# Lire une plage
ema_period = manager.get_range("ema", "period")
print(f"EMA: {ema_period.min}-{ema_period.max}")

# Modifier
manager.update_range("ema", "period", min_val=3, max_val=300)
manager.save_ranges(backup=True)  # Backup auto créé
```

## 📋 Exemples Courants

### Scalping (timeframes courts)

```powershell
python tools\edit_ranges.py set ema.short_period --min 3 --max 15
python tools\edit_ranges.py set ema.long_period --min 10 --max 50
python tools\edit_ranges.py set rsi.overbought --min 75 --max 85
```

### Trading Long Terme

```powershell
python tools\edit_ranges.py set ema.short_period --min 20 --max 50
python tools\edit_ranges.py set ema.long_period --min 50 --max 200
python tools\edit_ranges.py set bollinger.std_dev --min 2.0 --max 4.0
```

### Réduire Espace de Recherche (Sweep Rapide)

```python
from utils.range_manager import get_global_range_manager

manager = get_global_range_manager()

# Plages plus étroites = moins de combinaisons
manager.update_range("ema", "short_period", min_val=10, max_val=15)
manager.update_range("ema", "long_period", min_val=40, max_val=50)

# Steps plus grands = moins de valeurs
manager.update_range("rsi", "period", step=2)  # Au lieu de 1

manager.save_ranges()
```

## ⚠️ Sécurité

- ✅ **Backup automatique** : `.toml.bak` créé avant chaque modification
- ✅ **Validation** : Vérification min < max, default dans range, step > 0
- ✅ **Restauration** : `move config\indicator_ranges.toml.bak config\indicator_ranges.toml`

## 📚 Documentation Complète

→ Voir `docs/RANGE_EDITOR_GUIDE.md` (800+ lignes)

## 🆘 Problèmes Fréquents

### "Module tomli not found"
```powershell
pip install tomli tomli-w
```

### "Fichier de configuration non trouvé"
```powershell
# Restaurer depuis backup
move config\indicator_ranges.toml.bak config\indicator_ranges.toml

# Ou depuis Git
git checkout config/indicator_ranges.toml
```

### Modifications non appliquées
1. Recharger Streamlit (Ctrl+R)
2. Redémarrer l'application
3. Vérifier que le fichier a bien été sauvegardé

## 🎯 Fichiers Importants

- `config/indicator_ranges.toml` - Configuration principale (677 lignes)
- `utils/range_manager.py` - Module core (600+ lignes)
- `tools/edit_ranges.py` - CLI (400+ lignes)
- `ui/range_editor.py` - Interface Streamlit (500+ lignes)
- `docs/RANGE_EDITOR_GUIDE.md` - Guide complet

## 💡 Astuces

- Utilisez le **mode dry-run** pour tester sans modifier : `--dry-run`
- Le **mode interactif** permet de modifier plusieurs plages sans relancer : `interactive`
- L'**interface Streamlit** affiche les modifications en temps réel avec validation
- Les **backups automatiques** permettent de revenir en arrière facilement

---

**Version** : 1.0.0
**Date** : 03/02/2026
**Support** : Voir AGENTS.md - Cahier de Maintenance
