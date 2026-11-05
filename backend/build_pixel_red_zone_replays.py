"""Build compact, source-verified replay fixtures from the checked-in ESPN audit."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "docs/research/fixtures/pixel-red-zone-2026-11-01"
OUTPUT_DIR = ROOT / "backend/fixtures/pixel_red_zone"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pixel_red_zone import normalize_summary  # noqa: E402


def build() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = json.loads((SOURCE_DIR / "capture_manifest.json").read_text())
    fixtures: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []

    for captured in manifest["fixtures"]:
        game_id = str(captured["event_id"])
        raw_path = SOURCE_DIR / captured["file"]
        raw_bytes = raw_path.read_bytes()
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if raw_sha256 != captured["sha256"]:
            raise ValueError(f"Raw ESPN fixture hash mismatch for {game_id}")

        raw = json.loads(raw_bytes)
        if str((raw.get("header") or {}).get("id")) != game_id:
            raise ValueError(f"ESPN header ID mismatch for {game_id}")
        if not captured.get("score_reconciliation", {}).get("matches"):
            raise ValueError(f"Independent scoreboard reconciliation failed for {game_id}")

        existing_path = OUTPUT_DIR / f"{game_id}.json"
        if existing_path.exists():
            replay = json.loads(existing_path.read_text())
        else:
            replay = normalize_summary(
                raw, game_id=game_id,
                observed_at_utc=captured["captured_at_utc"], mode="replay",
            )
            for event in replay["events"]:
                for key in ("raw_play", "raw_start", "raw_end", "source_order"):
                    event.pop(key, None)
            replay["archive"] = {
                "label": "REPLAY",
                "captured_at_utc": captured["captured_at_utc"],
                "raw_fixture_sha256": raw_sha256,
                "raw_fixture_file": raw_path.name,
                "score_reconciled_to_independent_espn_scoreboard": True,
            }

        if replay.get("mode") != "replay" or replay.get("game", {}).get("game_id") != game_id:
            raise ValueError(f"Replay identity mismatch for {game_id}")
        if len(replay.get("events", [])) != captured["plays"]:
            raise ValueError(f"Replay event count mismatch for {game_id}")
        event_ids = [event.get("source", {}).get("event_id") for event in replay["events"]]
        if not all(event_ids) or len(set(event_ids)) != len(event_ids):
            raise ValueError(f"Replay source IDs are missing or duplicated for {game_id}")
        if replay["game"]["score"] != captured["score_reconciliation"]["summary_header"]:
            raise ValueError(f"Final score mismatch for {game_id}")
        if replay.get("archive", {}).get("raw_fixture_sha256") != raw_sha256:
            raise ValueError(f"Replay source hash mismatch for {game_id}")
        if replay.get("archive", {}).get("score_reconciled_to_independent_espn_scoreboard") is not True:
            raise ValueError(f"Replay scoreboard reconciliation missing for {game_id}")

        fixtures.append({"game_id": game_id, "payload": replay})

        game = replay["game"]
        away = game["teams"]["away"]
        home = game["teams"]["home"]
        catalog.append({
            "game_id": game_id,
            "date": game["date"],
            "label": f"{away['abbreviation']} at {home['abbreviation']}",
            "away_team": away["name"],
            "home_team": home["name"],
            "event_count": len(replay["events"]),
            "raw_fixture_sha256": raw_sha256,
        })

    fixtures.sort(key=lambda row: row["game_id"])
    catalog.sort(key=lambda row: (row["date"] or "", row["game_id"]))
    return fixtures, catalog


def main() -> None:
    fixtures, catalog = build()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for fixture in fixtures:
        path = OUTPUT_DIR / f"{fixture['game_id']}.json"
        if not path.exists():
            path.write_text(json.dumps(fixture["payload"], ensure_ascii=False, separators=(",", ":")) + "\n")
    (OUTPUT_DIR / "index.json").write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"Built {len(fixtures)} ESPN replay fixtures and the archive index.")


if __name__ == "__main__":
    main()
