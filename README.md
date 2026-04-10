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

## Hygiene de contexte pour les agents

Ce `README.md` reste volontairement compact.

Les zones suivantes sont considerees comme bruit de contexte par defaut et doivent etre exclues de l'indexation/search agentique du workspace :

- artefacts et resultats runtime
- sandbox, labs et archives UI
- documentation massive ou historique
- catalogues JSON generes
- fichiers de backup et journaux lourds

Les reglages VS Code du depot et `.copilotignore` portent cette politique pour garder un contexte de travail plus cible.
