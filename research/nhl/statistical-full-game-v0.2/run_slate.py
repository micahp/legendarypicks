#!/usr/bin/env python3
"""Run multiple frozen NHL pregame matchups with one verified training load."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path


HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location("nhl_team_player_sim_v02",HERE/"nhl_team_player_sim.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load v0.2 NHL simulator")
SIM=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=SIM
SPEC.loader.exec_module(SIM)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slate",type=Path,required=True)
    parser.add_argument("--out-dir",type=Path,required=True)
    parser.add_argument("--simulations",type=int,default=500)
    parser.add_argument("--base-seed",type=int,default=31415)
    parser.add_argument("--db",type=Path,default=SIM.DEFAULT_DB)
    parser.add_argument("--data-root",type=Path,default=SIM.v01.DEFAULT_DATA_ROOT)
    parser.add_argument("--verify-reproducibility",action="store_true")
    args=parser.parse_args()
    if args.simulations<1:
        parser.error("--simulations must be positive")
    slate=json.loads(args.slate.read_text(encoding="utf-8"))
    cutoff=slate["as_of_utc"]
    for row in slate["games"]:
        if row["scheduled_start_utc"]<=cutoff:
            raise ValueError(f"{row['game_key']}: scheduled start is not after frozen pregame cutoff")

    started=time.monotonic()
    corpus=SIM.v01.load_corpus(args.data_root,SIM.v01.TRAIN_SEASONS)
    shift_manifest=SIM.load_shift_manifest()
    quality_model=SIM.fit_shot_quality(corpus)
    args.out_dir.mkdir(parents=True,exist_ok=True)
    for index,row in enumerate(slate["games"]):
        inputs=SIM.prepare_pregame(args.db,game_key=row["game_key"],game_date=slate["game_date"],
            start_utc=row["scheduled_start_utc"],as_of_utc=cutoff,
            home=row["home_team"],away=row["away_team"])
        inputs.snapshot["schedule_source"]=slate["schedule_source"]
        inputs.snapshot["scheduled_start_local"]=row["scheduled_start_local"]
        inputs.snapshot["schedule_cutoff_note"]="Included only because scheduled puck drop follows the frozen cutoff."
        base_seed=args.base_seed+index*1_000_000
        distribution=SIM.simulate_matchup(corpus,inputs,base_seed,args.simulations,shift_manifest,quality_model)
        if args.verify_reproducibility:
            repeated=SIM.generate_game(corpus,inputs,base_seed,shift_manifest,quality_model)
            if json.dumps(repeated,sort_keys=True,separators=(",",":")) != json.dumps(
                    distribution["example_game"],sort_keys=True,separators=(",",":")):
                raise ValueError(f"{row['game_key']}: same-seed generated record was not byte-stable")
        distribution["schedule"]={"source":slate["schedule_source"],"scheduled_start_utc":row["scheduled_start_utc"],
            "scheduled_start_local":row["scheduled_start_local"],"frozen_as_of_utc":cutoff}
        distribution["reproducibility_verified"]=bool(args.verify_reproducibility)
        distribution["training_population"]={"eligible_by_start_season":corpus.eligible_by_season,
            "training_start_seasons":list(SIM.v01.TRAIN_SEASONS),
            "excluded_development_seasons":list(SIM.v01.DEVELOPMENT_SEASONS),
            "excluded_exposed_seasons":list(SIM.v01.EXCLUDED_SEASONS),
            "quarantined_source_seasons":list(SIM.v01.SOURCE_QUALITY_QUARANTINE_SEASONS)}
        model_suffix=SIM.MODEL_VERSION.rsplit("-",1)[-1]
        out=args.out_dir/f"{row['game_key']}-v0.2-{model_suffix}.json"
        SIM._write_json(out,distribution)
        print(json.dumps({"output":str(out),"game_key":row["game_key"],
            "simulations":args.simulations,"winner_probability":distribution["summary"]["winner_probability"],
            "mean_goals":{side:distribution["summary"]["team_prediction"][side]["mean_goals"]
                          for side in ("home","away")},
            "runtime_seconds":distribution["runtime_seconds"]},sort_keys=True),flush=True)
    print(json.dumps({"slate":str(args.slate),"game_count":len(slate["games"]),
        "total_wall_runtime_seconds":round(time.monotonic()-started,3),
        "eligible_training_games":corpus.eligible_by_season},sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        raise SystemExit(2)
