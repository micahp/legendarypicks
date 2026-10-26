#!/usr/bin/env python3
"""Time one real historical target per preregistration before freezing MC budget.

This smoke reports only adapter coverage, generated-event counts, and runtime. It
does not calculate or print target-game scoring metrics.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    sim = _load("nhl_v02b_smoke", HERE / "nhl_game_state_sim.py")
    b0 = _load("nhl_alpha2_smoke", ROOT / "research/nhl/statistical-full-game-v0.2/nhl_team_player_sim.py")
    adapter = _load("nhl_historical_adapter_smoke", HERE / "historical_adapter.py")
    seasons = tuple(sim.v01.TRAIN_SEASONS) + tuple(sim.v01.DEVELOPMENT_SEASONS)
    load_started = time.monotonic()
    all_corpus = sim.v01.load_corpus(sim.v01.DEFAULT_DATA_ROOT, seasons)
    train_corpus = copy.copy(all_corpus)
    train_corpus.games = {key: game for key, game in all_corpus.games.items()
                          if game.start_season in sim.v01.TRAIN_SEASONS and sim.v01._eligible_game(game)}
    if len(train_corpus.games) != sum(all_corpus.eligible_by_season[y]
                                      for y in sim.v01.TRAIN_SEASONS):
        raise ValueError("training-only donor corpus failed the frozen eligibility count")
    boxscore_manifest = adapter.load_boxscore_manifest(sim.v01)
    days = adapter.eligible_history_days(all_corpus, boxscore_manifest, seasons)
    shift_manifest = sim.load_shift_manifest()
    b0_quality = b0.fit_shot_quality(train_corpus)
    b1_quality = sim.fit_shot_quality(train_corpus)
    transition_model = sim.fit_event_transition_model(train_corpus)
    source_prep_seconds = time.monotonic() - load_started

    history = adapter.ForwardOnlyHistory()
    selected = None
    for game_date, games in days.items():
        targets = [game for game in games if game.start_season == 2021]
        # Inputs for every game on the date are built before any same-day results
        # are added to the history accumulator.
        target_inputs = []
        for game in targets:
            row = boxscore_manifest[str(game.game_id)]
            try:
                inputs = history.make_inputs(sim=sim, game_key=str(game.game_id),
                    game_date=game_date, home=str(row["canonical_home_team"]),
                    away=str(row["canonical_away_team"]))
            except ValueError as exc:
                target_inputs.append({"game": game, "row": row, "error": str(exc)})
            else:
                target_inputs.append({"game": game, "row": row, "inputs": inputs})

        # Choose the earliest target with a supported prior-appearance roster.
        # Team labels come from the independent manifest; no target boxscore body
        # or outcome is loaded for this smoke.
        selected = next((item for item in target_inputs if "inputs" in item), None)
        if selected is not None:
            break

        for game in games:
            if game.start_season in sim.v01.TRAIN_SEASONS:
                row = boxscore_manifest[str(game.game_id)]
                box = adapter.read_verified_boxscore(game, row, sim.v01.DEFAULT_BOXSCORE_ROOT)
                history.add_game(game, row, box)

    if selected is None:
        raise ValueError("no 2021 eligible target has complete prior-appearance team rosters")

    inputs = selected["inputs"]
    result = []
    for name, module, quality, transitions in (
        ("B0-alpha2", b0, b0_quality, None),
        ("B1", sim, b1_quality, None),
        ("B2", sim, b1_quality, transition_model),
    ):
        started = time.monotonic()
        generated = module.generate_game(train_corpus, inputs, 31415,
                                         shift_manifest, quality, transitions) if name != "B0-alpha2" \
            else module.generate_game(train_corpus, inputs, 31415, shift_manifest, quality)
        elapsed = time.monotonic() - started
        result.append({"candidate": name, "generation_seconds": round(elapsed, 4),
                       "event_count": len(generated["events"]),
                       "game_record_complete": generated.get("record_complete", True),
                       "same_seed_reproduction_not_run": True})
    print(json.dumps({
        "mode": "historical-runtime-smoke-only-no-score-metrics",
        "target_game_id": str(selected["game"].game_id),
        "target_date": selected["row"]["game_date"],
        "home_team": selected["row"]["canonical_home_team"],
        "away_team": selected["row"]["canonical_away_team"],
        "history_games_before_target": len(history.games_added),
        "history_latest_game_date": history.latest_game_date,
        "eligible_2021_games": all_corpus.eligible_by_season.get(2021, 0),
        "source_preparation_seconds": round(source_prep_seconds, 3),
        "candidate_generation": result,
        "target_outcomes_opened": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
