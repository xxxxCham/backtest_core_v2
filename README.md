# Backtest Core V2

Moteur de backtest multi-LLM avec acceleration GPU pour strategies de trading algorithmique.

## Portee du depot

Le workspace contient plusieurs couches :

- moteur de backtest et persistance des runs
- orchestration LLM mono et multi-roles
- interface Streamlit
- strategies et indicateurs
- zones experimentales, archives et artefacts generes

Le point important pour les assistants VS Code : toute la racine n'est pas du contexte utile par defaut.

## Points d'entree utiles

- `backtest/` : moteur, execution, metriques, stockage
- `agents/` : Builder, orchestrateur, roles LLM, instrumentation
- `core/llm_multi/` : orchestration multi-LLM
- `ui/` : application Streamlit et vues principales
- `strategies/` : strategies versionnees
- `indicators/` : indicateurs techniques
- `cli/` : commandes utilisateur

## Documentation utile

- [AGENTS.md](AGENTS.md) : regles projet et resume operatoire compact
- [AGEND_HISTORY.md](AGEND_HISTORY.md) : journal complet append-only ; exclu de l'indexation Copilot
- `GUIDE_CREATION_NOUVELLE_STRATEGIE.md` : guide principal pour ajouter une strategie
- `examples/README.md` : point d'entree des exemples legers versionnes
- `examples/end_to_end/README.md` : mini parcours de bout en bout

## Exports locaux des sessions Builder

Les sauvegardes locales des sessions Builder restent dans le dossier runtime prévu à cet effet, sous forme de fichiers :

- `<builder_sessions_root>\<session_id>\session_summary.json`

Il y a bien un `session_summary.json` par dossier de session. Le dépôt ne doit pas contenir de copie de ces sauvegardes. Pour produire un export analytique local sans dupliquer les sessions dans le workspace Git, utiliser :

```powershell
python tools\export_builder_session_summary_backup.py
```

La sortie par défaut est écrite hors dépôt dans :

`%USERPROFILE%\Documents\backtest_results\_builder_session_summary_exports\`

Elle contient un manifeste CSV à chemins relatifs, une archive NDJSON compressée contenant un enregistrement compact par session, et des vues analytiques plates. L'option `--include-full-payload` existe pour un export local complet, mais elle ne doit pas être utilisée pour créer un artefact versionné.

- `runs_summary.csv` : une ligne par session avec compteurs par cohorte.
- `run_iterations.csv` : une ligne par itération avec flags canonique/fallback, cause de fallback et robustesse.
- `runtime_events.csv` : erreurs et événements runtime extraits des itérations.
- `benchmark_cohorts.csv` : agrégats par statut, modèle, symbole, timeframe et diagnostic.
- `benchmark_candidates.csv` : itérations canoniques robustes classées pour baseline v2/v3.
- `builder_benchmark_report.md` : synthèse Markdown lisible des cohortes et meilleurs candidats.

## Hygiene de contexte pour les agents

Ce `README.md` reste volontairement compact.

Les zones suivantes sont considerees comme bruit de contexte par defaut et doivent etre exclues de l'indexation/search agentique du workspace :

- artefacts et resultats runtime
- sandbox, labs et archives UI
- documentation massive ou historique
- catalogues JSON generes
- fichiers de backup et journaux lourds

Les reglages VS Code du depot et `.copilotignore` portent cette politique pour garder un contexte de travail plus cible.
