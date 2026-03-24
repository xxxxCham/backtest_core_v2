from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.builder_view import (
    _AUTONOMOUS_SUPERVISOR_STATE_FILE,
    _load_autonomous_runtime_state,
    _load_autonomous_supervisor_state,
    _recover_autonomous_history_from_disk,
    _save_autonomous_supervisor_state,
)


def main() -> int:
    payload = _load_autonomous_supervisor_state()
    history = list(payload.get("history", []) or [])
    supervisor = dict(payload.get("supervisor", {}) or {})
    runtime_state = _load_autonomous_runtime_state()

    recovered_history, changed = _recover_autonomous_history_from_disk(
        history,
        runtime_state=runtime_state,
    )

    if not changed:
        print("Aucune ligne autonome à réparer.")
        return 0

    before_empty = sum(
        1 for row in history if not str(row.get("session_id", "") or "").strip()
    )
    after_empty = sum(
        1 for row in recovered_history if not str(row.get("session_id", "") or "").strip()
    )

    state_path = Path(_AUTONOMOUS_SUPERVISOR_STATE_FILE)
    backup_path = state_path.with_suffix(state_path.suffix + ".bak")
    shutil.copy2(state_path, backup_path)

    _save_autonomous_supervisor_state(recovered_history, supervisor)

    print(
        json.dumps(
            {
                "state_file": str(state_path),
                "backup_file": str(backup_path),
                "history_rows": len(history),
                "empty_session_id_before": before_empty,
                "empty_session_id_after": after_empty,
                "repaired_rows": before_empty - after_empty,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())