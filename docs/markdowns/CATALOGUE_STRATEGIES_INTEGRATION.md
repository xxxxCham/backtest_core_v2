# Intégration du Catalogue de Stratégies

## 🎯 Résumé des modifications

Le système de catalogue de stratégies a été intégré dans la sidebar de l'UI Streamlit pour remplacer progressivement l'ancien système de sélection classique.

## ✅ Problèmes corrigés

### 1. Affichage en double
- **Avant** : Le panel catalogue n'était appelé nulle part, créant une confusion
- **Après** : Le panel s'affiche uniquement en mode "🗂️ Catalogue" et hors mode Builder

### 2. Sélections redondantes (Token/Stratégie)
- **Avant** : Les filtres Token/Timeframe ressemblaient à des sélections obligatoires
- **Après** : Filtres clairement marqués comme optionnels et placés dans un expander "Filtres avancés"

### 3. Double système confus
- **Avant** : Coexistence de l'ancien multiselect et du nouveau catalogue
- **Après** : Mode de sélection explicite avec radio button (Classique vs Catalogue)

## 📋 Changements techniques

### Fichiers modifiés

#### 1. `ui/sidebar.py`
- **Ajout** : Import de `render_strategy_catalog_panel`
- **Modification** : Section "🎯 Stratégie" avec mode de sélection (Classique/Catalogue)
- **Ajout** : Appel conditionnel au panel catalogue en fin de fonction

```python
# Nouveau mode de sélection
strategy_selection_mode = st.sidebar.radio(
    "Mode de sélection",
    ["📋 Classique", "🗂️ Catalogue"],
    ...
)
```

#### 2. `ui/components/strategy_catalog_panel.py`
- **Amélioration** : Labels clarifiés avec emojis et descriptions
- **Amélioration** : Filtres Token/Timeframe/Tags dans expander "Filtres avancés"
- **Amélioration** : Messages d'aide explicites sur le rôle des filtres
- **Amélioration** : Bouton "✅ Utiliser cette sélection" plus visible (type=primary)
- **Correction** : Récupération correcte des filtres depuis session_state

## 🚀 Guide d'utilisation

### Mode Classique (📋)
1. Sélectionner le mode "📋 Classique" dans la sidebar
2. Utiliser le multiselect classique pour choisir les stratégies
3. Configuration simple et directe

### Mode Catalogue (🗂️)
1. Sélectionner le mode "🗂️ Catalogue" dans la sidebar
2. Descendre jusqu'au panel "🗂️ Strategy Catalog" en bas de page
3. **Filtrer** (optionnel) :
   - Par catégorie : p1_builder_inbox, p2_auto_shortlist, etc.
   - Par statut : active, archived
   - Filtres avancés : Token, Timeframe, Tags (dans l'expander)
4. **Sélectionner** les stratégies en cochant les cases
5. **Appliquer** avec le bouton "✅ Utiliser cette sélection"
6. Les stratégies sélectionnées deviennent actives pour le backtest

### Classification des stratégies

Le système utilise 7 catégories pour organiser le cycle de vie :

| Catégorie | Description |
|-----------|-------------|
| `p1_builder_inbox` | Stratégies générées par le builder (inbox) |
| `p2_auto_shortlist` | Stratégies présélectionnées automatiquement (bonnes métriques) |
| `p3_watchlist` | Stratégies à surveiller (watchlist manuelle) |
| `p4_paper_candidate` | Candidates pour paper trading |
| `p5_live_active` | Actives en production |
| `p6_live_validated` | Validées après période de production |
| `p7_archived_rejected` | Archivées/rejetées |

### Déplacement de stratégies

1. Sélectionner une ou plusieurs stratégies (cases à cocher)
2. Choisir la catégorie de destination dans "📦 Déplacer vers catégorie"
3. Cliquer sur "📦 Move"

## 🔧 Architecture

### Backend
- `catalog/strategy_catalog.py` : CRUD sur le catalogue JSON
- `config/strategy_catalog.json` : Stockage persistant des entrées

### UI
- `ui/components/strategy_catalog_panel.py` : Panel de visualisation/filtrage
- `ui/sidebar.py` : Intégration dans la sidebar

### Flux de données

```
Builder Session
    ↓
upsert_from_builder_session()
    ↓
config/strategy_catalog.json (p1_builder_inbox ou p2_auto_shortlist)
    ↓
render_strategy_catalog_panel()
    ↓
Sélection utilisateur
    ↓
session_state["strategies_select"]
    ↓
Backtest
```

## 🐛 Problèmes connus et limitations

### Limitations actuelles
1. **Stratégies builder non exécutables** : Certaines stratégies générées par le builder ne sont pas encore enregistrées dans le registre de stratégies (field "runnable" = "no")
2. **Résolution de stratégie** : Le système tente de résoudre l'ID de stratégie depuis le champ `note` (patterns `id:` ou `archetype:`)

### Workarounds
- Les stratégies non exécutables sont automatiquement ignorées lors de l'application de la sélection
- Un message d'avertissement indique combien de stratégies ont été ignorées

## 📊 Métriques et indicateurs

Le panel affiche pour chaque stratégie :
- **Sharpe** : Sharpe ratio
- **Return (%)** : Retour total en pourcentage
- **PnL ($)** : Profit/Loss absolu
- **Trades** : Nombre total de trades
- **Runnable** : yes/no selon disponibilité dans le registre

Les métriques sont extraites depuis :
1. `last_metrics_snapshot` (snapshot du backtest)
2. `meta.best_sharpe`, `meta.best_trades`, etc. (fallback)
3. `sandbox_strategies/{session_id}/session_summary.json` (fallback ultime)

## 🔮 Évolutions futures

### À implémenter
- [ ] Export du catalogue en CSV/Excel
- [ ] Filtres par plage de métriques (Sharpe > 1.0, etc.)
- [ ] Comparaison visuelle de plusieurs stratégies
- [ ] Notes/annotations par stratégie
- [ ] Historique des déplacements de catégories
- [ ] Auto-archivage des stratégies avec métriques négatives

### Améliorations possibles
- [ ] Intégration avec le système de versioning des stratégies
- [ ] Liens directs vers les sessions builder dans sandbox_strategies/
- [ ] Graphiques de distribution des métriques par catégorie
- [ ] Alertes sur stratégies prometteuses (auto-shortlist notifications)

## 📝 Notes de développement

### Conventions de code
- Les catégories suivent le pattern `p{N}_{name}` pour garantir l'ordre
- Les IDs d'entrées suivent le format `{strategy_name}|{symbol}|{timeframe}|{params_hash}`
- Les filtres utilisent `st.session_state` pour persister entre reruns

### Tests
- Tester les deux modes (Classique/Catalogue) pour vérifier la transition
- Vérifier que les stratégies sélectionnées depuis le catalogue sont bien appliquées
- Tester le déplacement de stratégies entre catégories
- Vérifier l'affichage avec catalogue vide

## 🆘 Dépannage

### Le panel catalogue ne s'affiche pas
- Vérifier que le mode "🗂️ Catalogue" est sélectionné dans la sidebar
- Vérifier que vous n'êtes pas en mode "🏗️ Strategy Builder"

### Aucune stratégie dans le catalogue
- Le catalogue se remplit automatiquement quand le builder crée des stratégies
- Lancer au moins une session builder pour populer le catalogue

### Stratégies non exécutables
- C'est normal pour les stratégies générées mais non encore enregistrées
- Utiliser le système de création de stratégies depuis le builder pour les enregistrer

---

**Version** : 1.0
**Date** : 2026-02-24
**Auteur** : Claude Sonnet 4.5
