# 🎯 Prompt pour Nouvelle Session : Filtrage des Données de Listing

## Contexte Rapide

J'ai un système de backtesting avec Numba qui teste 1.7M+ combinaisons de paramètres en 4-5 minutes.

**Problème actuel** : Les résultats sont faussés par les données de **price discovery** lors du listing du token.

---

## 📊 Données du Problème

### Token Testé
- **Symbole** : AVAXUSDC
- **Timeframe** : 15m
- **Période** : 2020-09-22 06:30 à 2026-01-31
- **Fichier** : `D:/my_soft/gestionnaire_telechargement_multi-timeframe/processed/parquet/AVAXUSDC_15m.parquet`

### Anomalies Détectées

**Première barre (2020-09-22 06:30)** :
```
Prix : 0.85$ → 6.00$ en 15 minutes (+605%)
Range premiers jours : 0.85$ - 7.00$ (+723%)
Volume : 50× plus élevé que données récentes
Mouvements > 20% en 15min : 1% (vs 0% aujourd'hui)
```

**Impact** :
- La stratégie génère +444% de PnL
- Mais la majeure partie vient des premières heures/jours (données artificielles)
- Sur données récentes (2024-2026), la stratégie PERD de l'argent

---

## 🎯 Objectif

Ajouter un **filtre de "warmup period"** dans l'UI Streamlit pour **exclure automatiquement** les N premières heures/jours de données après le listing.

---

## 📋 Tâches à Réaliser

### 1. Ajouter Option dans la Sidebar (`ui/sidebar.py`)

```python
# Section: Filtrage des données
st.subheader("🛡️ Filtrage des Données")

enable_warmup = st.checkbox(
    "Exclure période de listing (warmup)",
    value=True,
    help="Ignore les premières heures/jours après listing (volatilité anormale)"
)

if enable_warmup:
    warmup_hours = st.number_input(
        "Heures à exclure après listing",
        min_value=0,
        max_value=168,  # 1 semaine max
        value=24,  # 24h par défaut
        step=6,
        help="Nombre d'heures à ignorer au début des données"
    )
else:
    warmup_hours = 0

# Retourner warmup_hours dans la configuration
```

### 2. Appliquer le Filtre dans `ui/main.py`

```python
# Avant le backtest/sweep, filtrer les données
if warmup_hours > 0:
    # Convertir timestamp en datetime si nécessaire
    if 'timestamp' in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('datetime')

    # Calculer date de début + warmup
    first_date = df.index[0]
    start_date_filtered = first_date + pd.Timedelta(hours=warmup_hours)

    # Filtrer
    df_original_len = len(df)
    df = df[df.index >= start_date_filtered]

    # Logger
    logger.info(f"Warmup filter applied: excluded {df_original_len - len(df):,} bars "
                f"({warmup_hours}h after {first_date})")

    # Afficher dans l'UI
    st.info(f"🛡️ Warmup: {df_original_len - len(df):,} bars exclues "
            f"({first_date} + {warmup_hours}h → {start_date_filtered})")
```

### 3. Option Alternative : Détection Automatique

Si l'utilisateur ne connaît pas le nombre d'heures optimal :

```python
# Détection automatique de la stabilisation du volume
def detect_stable_period(df, volume_col='volume', window=100, threshold=2.0):
    """
    Détecte quand le volume se stabilise après un listing.

    Retourne l'index de la première barre "stable".
    """
    volume_ma = df[volume_col].rolling(window).mean()

    # Trouver premier point où volume < threshold × moving average
    stable = df[volume_col] < volume_ma * threshold

    if stable.any():
        first_stable_idx = stable.idxmax()
        return first_stable_idx

    return df.index[0]

# Dans l'UI
if st.checkbox("Détection automatique du warmup"):
    stable_date = detect_stable_period(df)
    st.info(f"🔍 Période stable détectée à partir de : {stable_date}")
    df = df[df.index >= stable_date]
```

---

## 🧪 Tests à Faire

### Test 1 : Sans Filtre (Baseline)
```python
# Résultat attendu : +444% PnL (invalide)
warmup_hours = 0
```

### Test 2 : Avec Filtre 24h
```python
# Résultat attendu : PnL probablement négatif ou beaucoup plus faible
warmup_hours = 24
```

### Test 3 : Avec Filtre 48h
```python
warmup_hours = 48
```

### Test 4 : Détection Automatique
```python
# Comparer avec filtres manuels
```

---

## 📊 Métriques à Comparer

Avant/Après filtrage :

| Métrique | Sans Filtre | Avec Filtre 24h | Avec Filtre 48h |
|----------|-------------|-----------------|-----------------|
| PnL Total | +$44,495 | ? | ? |
| Sharpe | 2.08 | ? | ? |
| Max DD | 11.68% | ? | ? |
| Win Rate | 34.13% | ? | ? |
| Trades | 126 | ? | ? |
| Période | 2020-09 à 2026-01 | 2020-09 (+24h) à 2026-01 | 2020-09 (+48h) à 2026-01 |

**Objectif** : Trouver le filtre qui donne une **vraie performance reproductible**.

---

## 📁 Fichiers à Modifier

1. `ui/sidebar.py` - Ajouter option warmup
2. `ui/main.py` - Appliquer filtre avant backtest
3. `RESUME_PROBLEMES_ET_SOLUTIONS.md` - Documenter résultats

---

## 🎯 Critères de Succès

✅ L'utilisateur peut activer/désactiver le filtre warmup
✅ Le nombre d'heures est configurable
✅ Les données sont correctement filtrées avant le backtest
✅ L'UI affiche clairement combien de bars ont été exclues
✅ Les résultats changent significativement (PnL plus réaliste)

---

## 💡 Questions à Résoudre

1. **Où dans le code `ui/main.py` filtrer les données ?**
   - Avant l'appel à `run_numba_sweep()` ?
   - Dans `ui/helpers.py` ?

2. **Comment gérer les différents formats de données ?**
   - Index numérique vs DatetimeIndex
   - Colonne `timestamp` vs index datetime

3. **Faut-il appliquer le filtre aussi aux sweeps ProcessPoolExecutor ?**
   - Oui, cohérence nécessaire

---

## 🚀 Bonus : Validation Visuelle

Après implémentation, créer un graphique comparatif :

```python
# Graphique : Équité avec/sans filtre
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

# Sans filtre
ax1.plot(equity_no_filter, label='Sans filtre (+444%)')
ax1.set_title('Équité SANS filtre warmup')

# Avec filtre
ax2.plot(equity_with_filter, label='Avec filtre 24h (?%)')
ax2.set_title('Équité AVEC filtre warmup 24h')

plt.savefig('warmup_comparison.png')
```

---

## 📋 Checklist Finale

Avant de clore la session :
- [ ] Option warmup ajoutée dans sidebar
- [ ] Filtre appliqué dans main.py
- [ ] Tests effectués (0h, 24h, 48h)
- [ ] Résultats documentés dans tableau comparatif
- [ ] Graphique comparatif créé
- [ ] Documentation mise à jour

---

**Fichiers de référence** :
- `RESUME_PROBLEMES_ET_SOLUTIONS.md` - Contexte complet
- `backtest/sweep_numba.py` - Code du sweep optimisé
- `ui/sidebar.py` - Configuration UI
- `ui/main.py` - Logique principale
