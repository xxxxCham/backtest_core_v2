from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "examples" / "end_to_end" / "data"


BTCUSDT_1H = [
    ["2025-01-01T00:00:00Z", 42000, 42120, 41920, 42080, 1250],
    ["2025-01-01T01:00:00Z", 42080, 42240, 42010, 42190, 1325],
    ["2025-01-01T02:00:00Z", 42190, 42310, 42110, 42260, 1180],
    ["2025-01-01T03:00:00Z", 42260, 42390, 42180, 42210, 1090],
    ["2025-01-01T04:00:00Z", 42210, 42440, 42190, 42380, 1415],
    ["2025-01-01T05:00:00Z", 42380, 42510, 42310, 42460, 1510],
    ["2025-01-01T06:00:00Z", 42460, 42520, 42340, 42400, 1280],
    ["2025-01-01T07:00:00Z", 42400, 42480, 42290, 42360, 1210],
]

ETHUSDT_4H = [
    ["2025-01-01T00:00:00Z", 3180, 3205, 3168, 3198, 8420],
    ["2025-01-01T04:00:00Z", 3198, 3224, 3190, 3212, 8015],
    ["2025-01-01T08:00:00Z", 3212, 3236, 3204, 3228, 7790],
    ["2025-01-01T12:00:00Z", 3228, 3248, 3215, 3236, 7555],
    ["2025-01-01T16:00:00Z", 3236, 3255, 3222, 3244, 7340],
    ["2025-01-01T20:00:00Z", 3244, 3262, 3235, 3254, 7105],
    ["2025-01-02T00:00:00Z", 3254, 3270, 3242, 3261, 6990],
    ["2025-01-02T04:00:00Z", 3261, 3284, 3250, 3276, 7210],
]


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        writer.writerows(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(OUTPUT_DIR / "ohlcv_BTCUSDT_1h.csv", BTCUSDT_1H)
    _write_csv(OUTPUT_DIR / "ohlcv_ETHUSDT_4h.csv", ETHUSDT_4H)
    print(f"Samples generated in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()