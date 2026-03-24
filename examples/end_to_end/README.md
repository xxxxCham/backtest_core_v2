# Mini Parcours De Bout En Bout

Ce dossier montre une vue compacte du systeme sans embarquer de gros artefacts.

## Ce que vous trouvez ici

- `data/` : deux petits DataFrames OHLCV en CSV (`BTCUSDT 1h` et `ETHUSDT 4h`).
- `stores/result_storage_native/` : exemple de run au format natif `ResultStorage`.
- `stores/result_store_v3/` : exemple de layout canonique `BacktestStoreV3` avec `runs/<run_id>/...` et exports derives `index.csv` / `index.json`.
- `stores/legacy_runner_manifest/` : exemple d'un run de type manifest historique (`metadata.json` + `metrics.json` + `config_snapshot.json`).

## Pourquoi ce format

- Les fichiers sont textuels et courts pour etre lisibles dans GitHub.
- Les artefacts reconstituent les formats majeurs du depot sans versionner de gros Parquet.
- Les fichiers `equity.csv`, `trades.csv` et `returns.csv` servent ici de miroirs lisibles ; en production, le layout canonique v3 ecrit surtout des `.parquet`.

## Lecture rapide

1. Ouvrir `data/ohlcv_BTCUSDT_1h.csv` ou `data/ohlcv_ETHUSDT_4h.csv` pour voir le format OHLCV attendu.
2. Ouvrir `stores/result_storage_native/native_run_btc_1h/metadata.json` pour voir le format historique/natif chargeable par `ResultStorage`.
3. Ouvrir `stores/result_store_v3/runs/v3_run_eth_4h/metadata.json` puis `stores/result_store_v3/index.csv` pour voir le layout et l'index v3.
4. Ouvrir `stores/legacy_runner_manifest/run_manifest_btc_1h/metadata.json` et `metrics.json` pour voir un artefact runner historique distinct.

## Regeneration des CSV OHLCV

Le script `data/sample_data/generate_sample.py` regenere les deux petits jeux OHLCV de ce dossier.