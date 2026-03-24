# Exemples Versionnes

Ce dossier regroupe des exemples volontairement legers, lisibles directement sur GitHub.

Contenu principal :

- `example_trade_analytics.py` : exemple executable d'analyse enrichie des trades.
- `end_to_end/README.md` : vue d'ensemble miniature du systeme, avec petits jeux OHLCV et exemples de resultats provenant de plusieurs couches de stockage.

Objectif :

- montrer le format attendu des DataFrames OHLCV,
- illustrer les artefacts produits par `ResultStorage`, `ResultStore` et les manifests legacy,
- fournir des fixtures textuelles faciles a auditer sans embarquer de gros binaires dans le depot.