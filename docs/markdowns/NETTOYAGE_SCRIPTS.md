# 🧹 NETTOYAGE DES SCRIPTS DE LANCEMENT

## Situation Actuelle
**10 fichiers .bat** à la racine → Confusion !

## Décision
**GARDER** : `run_streamlit.bat` (optimisé avec nettoyage cache)
**ARCHIVER** : Tous les autres dans `scripts_old/`

---

## Fichiers à Archiver

| Fichier | Description | Action |
|---------|-------------|--------|
| `Lancer_Interface_Streamlit.bat` | Ancien lanceur | → `scripts_old/` |
| `restart_streamlit.bat` | Script temporaire créé | → `scripts_old/` |
| `run_streamlit_multigpu.bat` | Version multi-GPU (non utilisée) | → `scripts_old/` |
| `start_streamlit_with_data.bat` | Lanceur avec data path | → `scripts_old/` |
| `benchmark.bat` | Tests performance | → `scripts_old/` |
| `test_environment.bat` | Test env | → `scripts_old/` |

**GARDER à la racine :**
- ✅ `run_streamlit.bat` (optimisé)
- ✅ `install.bat` (installation dépendances)
- ✅ `edit_ranges.bat` (utilitaire édition)

---

## Commande de Nettoyage

```cmd
mkdir scripts_old
move Lancer_Interface_Streamlit.bat scripts_old\
move restart_streamlit.bat scripts_old\
move run_streamlit_multigpu.bat scripts_old\
move start_streamlit_with_data.bat scripts_old\
move benchmark.bat scripts_old\
move test_environment.bat scripts_old\
move restart_ollama_multigpu.bat scripts_old\
```

---

## Après Nettoyage

À la racine, vous aurez SEULEMENT :
```
run_streamlit.bat    ← Lanceur principal optimisé
install.bat          ← Installation
edit_ranges.bat      ← Utilitaire
```

**Simple et clair !** ✅
