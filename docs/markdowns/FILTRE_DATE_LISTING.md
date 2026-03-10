# 🛡️ Solution : Filtrer les Données Pré-Listing

## Problème
Votre backtest inclut des données **avant le listing du token** → Trades fantômes avec gains artificiels.

## Solution 1 : Filtre Manuel (Rapide)

### Identifier la Date de Listing
1. Quel token utilisez-vous ? (visible dans les paramètres : XXXUSDC)
2. Vérifier sur Binance : https://www.binance.com/en/support/announcement/new-cryptocurrency-listing
3. Noter la date de listing

### Appliquer le Filtre dans l'UI

Avant de lancer un backtest, ajoutez dans `ui/sidebar.py` :

```python
# Dans la section "Configuration prête"
start_date = st.date_input(
    "📅 Date de début (ignorer données pré-listing)",
    value=pd.to_datetime("2024-01-01").date(),
    help="Filtrer les données avant cette date (ex: date de listing du token)"
)
```

Puis dans `ui/main.py`, avant le backtest :
```python
# Filtrer les données par date
if start_date:
    df = df[df.index >= pd.to_datetime(start_date)]
    st.info(f"📅 Données filtrées : {len(df):,} bars depuis {start_date}")
```

## Solution 2 : Détection Automatique

Ajouter une vérification de volume/liquidité :
```python
# Détecter le premier jour avec volume significatif
min_volume = df['volume'].quantile(0.25)  # 25e percentile
first_valid_date = df[df['volume'] > min_volume].index[0]
df = df[df.index >= first_valid_date]
```

## Solution 3 : Validation des Résultats

Pour vos résultats actuels :
1. Identifiez la date de listing (ex: 2024-03-15)
2. Relancez le backtest avec `df = df[df.index >= "2024-03-15"]`
3. Comparez les métriques :
   - Avant filtrage : +444% (invalide)
   - Après filtrage : ? (résultat réel)

---

## Vérification Rapide

**Quel token utilisez-vous ?**
- Si c'est un nouveau token (listé < 1 an), le problème est très probable
- Si c'est BTC/ETH (listés depuis des années), le problème est ailleurs

**Questions** :
1. Quel symbole ? (XXXUSDC)
2. Date de listing approximative ?
3. Période de vos données ? (2021-2026 ?)
