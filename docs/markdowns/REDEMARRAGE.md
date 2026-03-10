# 🔄 REDÉMARRAGE APRÈS REBOOT

## Problème
Après redémarrage, Python a rechargé l'**ancien code** (cache .pyc).
Performance revenue à 140 bt/s au lieu de 6,600 bt/s.

## Solution Rapide

### Windows
```cmd
cd d:\backtest_core
restart_streamlit.bat
```

### Ou Manuellement
```cmd
# 1. Tuer tous les Python
taskkill /F /IM python.exe

# 2. Nettoyer cache
python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"

# 3. Relancer
streamlit run ui\app.py --server.maxUploadSize 500
```

## Vérification

Une fois Streamlit lancé, dans la console vous devriez voir lors d'un sweep Numba :
```
[NUMBA] Construction vectorisée des 1,771,561 résultats...
  Progression: 100,000/1,771,561 (5.6%) • 800,000+ results/s
  Progression: 200,000/1,771,561 (11.3%) • 700,000+ results/s
  ...
⚡ Numba sweep TOTAL: 1,771,561 en 268s (6,600 bt/s)
```

Si vous voyez ça → ✅ Optimisations actives !
Si vous ne voyez pas "Construction vectorisée" → ❌ Cache pas nettoyé

## Performances Attendues

| Métrique | Valeur |
|----------|--------|
| Throughput | **6,000-7,000 bt/s** |
| Temps 1.7M | **4-5 minutes** |
| Construction | **2-3 secondes** |
| Feedback | Tous les 100K combos |

Si < 1,000 bt/s → cache Python pas nettoyé, relancer la procédure.
