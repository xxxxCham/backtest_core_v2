# Builder Session Summary GitHub Backup

- Generated at: `2026-04-26T00:24:12`
- Canonical source root: `C:\Users\o3-Pro\Documents\backtest_results\_builder_sessions`
- Canonical source shape: one `session_summary.json` per Builder session directory.
- Exported summaries: `2165`
- Skipped summaries: `1`
- Archive: `session_summaries.ndjson.gz`
- Manifest: `manifest.csv`
- Archive SHA256: `676ba96d189737f87d95d058222f81bb4ff976c700d5ef6dbaf98f199088b3c3`

The compressed NDJSON archive stores one JSON object per source session summary.
Each object contains `record_index`, `session_id`, `source_path`, `sha256`, and the original `payload`.

To inspect quickly:

```powershell
python - <<'PY'
import gzip, json
path = r'D:\backtest_core_v2\github_backups\builder_session_summaries\session_summaries.ndjson.gz'
with gzip.open(path, 'rt', encoding='utf-8') as handle:
    first = json.loads(next(handle))
print(first['session_id'])
PY
```
