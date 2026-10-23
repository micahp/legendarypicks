#!/usr/bin/env python3
"""Grouped development comparison of independent, interactive and constrained hockey movement."""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import subprocess
import time
from pathlib import Path

for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"

import numpy as np

SEED, BOOTSTRAPS, H = 20261023, 10_000, 45
RINK_X, RINK_Y = (-100.0, 100.0), (-42.5, 42.5)
ALPHA, FEATURE_VERSION = 0.1, "nhl-movement-features-v0.1"
T6=np.arange(6,dtype=float)
LIN6=np.linalg.pinv(np.column_stack((np.ones(6),T6)))
QUAD6=np.linalg.pinv(np.column_stack((np.ones(6),T6,T6*T6)))


def ridge_fit(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0); scale = x.std(axis=0); scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale; design = np.column_stack((np.ones(len(z)), z))
    gram = design.T @ design / len(z); rhs = design.T @ y / len(z)
    penalty = np.eye(len(gram)) * ALPHA; penalty[0, 0] = 0
    return np.linalg.solve(gram + penalty, rhs), mean, scale


def ridge_predict(model: tuple[np.ndarray, np.ndarray, np.ndarray], x: np.ndarray) -> np.ndarray:
    coef, mean, scale = model
    return np.column_stack((np.ones(len(x)), (x - mean) / scale)) @ coef


def q90(values: np.ndarray) -> float:
    ordered = np.sort(values)
    return float(ordered[min(len(ordered)-1, max(0, math.ceil(.90*(len(ordered)+1))-1))])


def json_default(value):
    if isinstance(value, np.generic):
        value = value.item()
    elif isinstance(value, np.ndarray):
        value = value.tolist()
    else:
        raise TypeError(f"not JSON serializable: {type(value).__name__}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numeric result cannot be serialized")
    return value


def thresholds(data: dict, train_games: list[int]) -> dict:
    def selected(values, groups, quantile):
        a = values[np.isin(groups, train_games)]
        if not len(a): raise RuntimeError("no training distribution for a movement constraint")
        return float(np.quantile(a, quantile))
    return {"max_displacement": selected(data["step_displacement"], data["step_group"], .995),
            "max_displacement_change": selected(data["adjacent_displacement_change"], data["change_group"], .995),
            "max_turn_radians": selected(data["heading_change_radians"], data["turn_group"], .995),
            "minimum_pair_separation": selected(data["nearest_player_distance"], data["nearest_group"], .05)}


def angle_delta(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def constrained_endpoint(pred: np.ndarray, pos: np.ndarray, x0: np.ndarray,
                         limits: dict) -> np.ndarray:
    out = pred.copy(); velocities = (out - pos) / 15.0
    previous = x0[:, :2].astype(float)
    for i in range(len(out)):
        vx, vy = velocities[i]; speed = math.hypot(vx, vy)
        cap = limits["max_displacement"]
        if speed > cap: vx *= cap / speed; vy *= cap / speed
        pvx, pvy = previous[i]; dx, dy = vx-pvx, vy-pvy
        delta = math.hypot(dx, dy); accel = limits["max_displacement_change"]
        if delta > accel:
            vx = pvx + dx * accel / delta; vy = pvy + dy * accel / delta
        if math.hypot(pvx, pvy) > .1 and math.hypot(vx, vy) > .1:
            old, new = math.atan2(pvy, pvx), math.atan2(vy, vx)
            turn = angle_delta(new, old); cap_turn = limits["max_turn_radians"]
            if abs(turn) > cap_turn:
                speed = math.hypot(vx, vy); a = old + math.copysign(cap_turn, turn)
                vx, vy = math.cos(a)*speed, math.sin(a)*speed
        out[i] = pos[i] + 15 * np.asarray([vx, vy])
    out[:, 0] = np.clip(out[:, 0], *RINK_X); out[:, 1] = np.clip(out[:, 1], *RINK_Y)
    return out


def project_pair_spacing(pred: np.ndarray, files: np.ndarray, cutoffs: np.ndarray, limits: dict) -> np.ndarray:
    out=pred.copy(); groups={}
    for i,key in enumerate(zip(files.tolist(),cutoffs.tolist())): groups.setdefault(key,[]).append(i)
    floor=limits["minimum_pair_separation"]
    for indexes in groups.values():
        for _ in range(2):
            for a in range(len(indexes)):
                for b in range(a+1,len(indexes)):
                    i,j=indexes[a],indexes[b];d=out[j]-out[i];r=float(np.linalg.norm(d))
                    if r>=floor:continue
                    if r<1e-9:d=np.asarray([1.,0.]);r=1.
                    push=(floor-r)/2;u=d/r;out[i]-=u*push;out[j]+=u*push
        for i in indexes:
            out[i,0]=np.clip(out[i,0],*RINK_X);out[i,1]=np.clip(out[i,1],*RINK_Y)
    return out


def baseline_features(history: list[list[float]]) -> np.ndarray:
    q = np.asarray(history[-6:], dtype=float)
    lin = LIN6 @ q
    quad = QUAD6 @ q
    return np.asarray([*lin[1], *(2*quad[2])], dtype=float)


def interaction_features(player: dict, state: dict) -> np.ndarray:
    kin = baseline_features(player["history"])
    puck = state.get("puck"); ph = state.get("puck_history") or []
    missing = puck is None
    puckdx = puck["x"]-player["x"] if puck else 0.0
    puckdy = puck["y"]-player["y"] if puck else 0.0
    pvx = puck["x"]-ph[-2][0] if puck and len(ph) >= 2 else 0.0
    pvy = puck["y"]-ph[-2][1] if puck and len(ph) >= 2 else 0.0
    def peers(team):
        weight = 0.; dx = dy = dvx = dvy = 0.; counts = [0,0,0]
        for other in state["players"]:
            if other["id"] == player["id"] or other["team"] != team: continue
            rx, ry = other["x"]-player["x"], other["y"]-player["y"]
            d = math.hypot(rx,ry); w = math.exp(-d/20); weight += w
            ov = baseline_features(other["history"])
            dx += rx*w; dy += ry*w; dvx += (ov[0]-kin[0])*w; dvy += (ov[1]-kin[1])*w
            for i,r in enumerate((10,20,40)): counts[i] += int(d <= r)
        vals = [dx/weight,dy/weight,dvx/weight,dvy/weight] if weight else [0.]*4
        return vals,counts
    mate,mc = peers(player["team"]); opponent = "Away" if player["team"] == "Home" else "Home"
    opp,oc = peers(opponent)
    return np.asarray([*kin,puckdx,puckdy,pvx,pvy,float(missing),*mate,*opp,*mc,*oc],dtype=float)


def predict_intent(state: dict, player: dict, model: dict) -> np.ndarray:
    x = baseline_features(player["history"]) if model["feature_count"] == 4 else interaction_features(player,state)
    z = (x - model["mean"]) / model["scale"]
    residual = np.asarray(model["coefficients"][0]) + z @ np.asarray(model["coefficients"][1:])
    endpoint = np.asarray([player["x"],player["y"]]) + 15*x[:2] + residual
    return (endpoint - np.asarray([player["x"],player["y"]])) / 15


def apply_m2(state: dict, intents: dict[str,np.ndarray], limits: dict) -> tuple[dict[str,np.ndarray],dict]:
    result = {}; counts = {"boundary_projections":0,"speed_projections":0,"turn_projections":0,
                           "delta_projections":0,"separation_projections":0}
    for p in state["players"]:
        dx,dy = intents[p["id"]]; speed=math.hypot(dx,dy)
        if speed > limits["max_displacement"]:
            f=limits["max_displacement"]/speed; dx*=f; dy*=f; counts["speed_projections"]+=1
        h=p["history"]; prior=np.asarray(h[-1])-np.asarray(h[-2]) if len(h)>=2 else np.zeros(2)
        dv=np.asarray([dx,dy])-prior; mag=float(np.linalg.norm(dv)); cap=limits["max_displacement_change"]
        if mag > cap:
            v=prior+dv*cap/mag; dx,dy=map(float,v); counts["delta_projections"]+=1
        if np.linalg.norm(prior)>.1 and math.hypot(dx,dy)>.1:
            old=math.atan2(prior[1],prior[0]); new=math.atan2(dy,dx); d=angle_delta(new,old)
            if abs(d)>limits["max_turn_radians"]:
                speed=math.hypot(dx,dy); a=old+math.copysign(limits["max_turn_radians"],d)
                dx,dy=math.cos(a)*speed,math.sin(a)*speed; counts["turn_projections"]+=1
        x,y=p["x"]+dx,p["y"]+dy
        cx,cy=np.clip(x,*RINK_X),np.clip(y,*RINK_Y)
        counts["boundary_projections"] += int(cx != x or cy != y)
        result[p["id"]]=np.asarray([cx,cy])
    floor=limits["minimum_pair_separation"]
    for _ in range(2):
        for i,p in enumerate(state["players"]):
            for q in state["players"][i+1:]:
                a,b=result[p["id"]],result[q["id"]]; dv=b-a; d=float(np.linalg.norm(dv))
                if d >= floor: continue
                if d < 1e-9: dv=np.asarray([1.,0.]);d=1.
                u=dv/d; push=(floor-d)/2
                aa=a-u*push;bb=b+u*push
                result[p["id"]]=np.asarray([np.clip(aa[0],*RINK_X),np.clip(aa[1],*RINK_Y)])
                result[q["id"]]=np.asarray([np.clip(bb[0],*RINK_X),np.clip(bb[1],*RINK_Y)])
                counts["separation_projections"]+=1
    return result,counts


def advance_puck(state: dict) -> None:
    hist=state.get("puck_history") or []; puck=state.get("puck")
    if puck is None or len(hist)<2:
        state["puck"]=None;state["puck_history"]=[];return
    x=puck["x"]+hist[-1][0]-hist[-2][0];y=puck["y"]+hist[-1][1]-hist[-2][1]
    if not (RINK_X[0]<=x<=RINK_X[1] and RINK_Y[0]<=y<=RINK_Y[1]):
        state["puck"]=None;state["puck_history"]=[];return
    state["puck"]={"x":x,"y":y,"generated_by":"constant_ordinal_displacement_helper"}
    state["puck_history"]=(hist+[[x,y]])[-6:]


def rollout(start: dict, m0: dict, m1: dict, limits: dict) -> tuple[dict,dict,dict]:
    state={"players":[{**p,"history":[list(xy) for xy in p["history"][-6:]]} for p in start["players"]],
           "puck":start.get("puck"),"puck_history":start.get("puck_history") or []}
    models={"M0":m0,"M1":m1,"M2":m1}; paths={k:{0:{p["id"]:[p["x"],p["y"]] for p in state["players"]}} for k in models}
    puck_paths={k:{0:state["puck"]} for k in models}
    constraint_counts={"boundary_projections":0,"speed_projections":0,"turn_projections":0,
                       "delta_projections":0,"separation_projections":0}
    for step in range(1,H+1):
        # Maintain independent evolving copies (kept outside the result dictionary).
        if step==1:
            model_states={name:{"players":[{**p,"history":[list(x) for x in p["history"]]} for p in state["players"]],
                                "puck":state["puck"],"puck_history":[list(x) for x in state["puck_history"]]}
                          for name in models}
        for name,model in models.items():
            s=model_states[name]
            intents={p["id"]:predict_intent(s,p,model) for p in s["players"]}
            if name=="M2":
                positions,counts=apply_m2(s,intents,limits)
                for k,v in counts.items(): constraint_counts[k]+=v
            else:
                positions={p["id"]:np.asarray([p["x"],p["y"]])+intents[p["id"]] for p in s["players"]}
            for p in s["players"]:
                xy=positions[p["id"]];p["x"],p["y"]=map(float,xy)
                p["history"]=(p["history"]+[[p["x"],p["y"]]])[-6:]
            advance_puck(s)
            paths[name][step]={p["id"]:[p["x"],p["y"]] for p in s["players"]}
            puck_paths[name][step]=s["puck"]
    return paths,puck_paths,constraint_counts


def frame_metrics(preds: dict, actual: dict, initial: dict, spacing_floor: float) -> dict:
    common=sorted(set(preds)&set(actual["players"]))
    if not common: return {"n_positions":0,"position_error_mean":None}
    initial_by_id={p["id"]:[p["x"],p["y"]] for p in initial["players"]}
    unexpected=set(common)-set(initial_by_id)
    if unexpected: raise RuntimeError(f"predicted/observed identity is absent from the cutoff state: {sorted(unexpected)[:3]}")
    err=[]; heading=[]; displacement=[]; pairerr=[]; spacing=[]; nearest=[]; simnearest=[]
    obspts=[];simpts=[]; ids=common
    for pid in ids:
        a=np.asarray(actual["players"][pid]); p=np.asarray(preds[pid]); err.append(float(np.linalg.norm(p-a)))
        init=initial_by_id[pid]; ad=a-np.asarray(init); pd=p-np.asarray(init)
        displacement.append(abs(float(np.linalg.norm(pd)-np.linalg.norm(ad))))
        if np.linalg.norm(ad)>=1 and np.linalg.norm(pd)>=1:
            heading.append(abs(angle_delta(math.atan2(pd[1],pd[0]),math.atan2(ad[1],ad[0]))))
        obspts.append(a);simpts.append(p)
    for i,pid in enumerate(ids):
        for qid in ids[i+1:]:
            da=np.linalg.norm(np.asarray(actual["players"][pid])-np.asarray(actual["players"][qid]))
            dp=np.linalg.norm(np.asarray(preds[pid])-np.asarray(preds[qid]))
            pairerr.append(abs(float(dp-da)))
    for team in ("Home","Away"):
        teamids=[p["id"] for p in initial["players"] if p["team"]==team and p["id"] in preds and p["id"] in actual["players"]]
        if len(teamids)>1:
            oa=[];sa=[]
            for i,a in enumerate(teamids):
                for b in teamids[i+1:]:
                    oa.append(np.linalg.norm(np.asarray(actual["players"][a])-actual["players"][b]))
                    sa.append(np.linalg.norm(np.asarray(preds[a])-preds[b]))
            spacing.append(abs(float(np.mean(sa)-np.mean(oa))))
    teams={p["id"]:p["team"] for p in initial["players"]}
    for pid in ids:
        opp=[q for q in ids if teams[q]!=teams[pid]]
        if opp:
            nearest.append(min(float(np.linalg.norm(np.asarray(actual["players"][pid])-actual["players"][q])) for q in opp))
            simnearest.append(min(float(np.linalg.norm(np.asarray(preds[pid])-np.asarray(preds[q]))) for q in opp))
    def occupancy(points):
        cells=np.zeros((20,9),float)
        for x,y in points:
            ix=min(19,max(0,int((x+100)/10)));iy=min(8,max(0,int((y+42.5)/10)))
            cells[ix,iy]+=1
        return cells/cells.sum() if cells.sum() else cells
    tv=.5*float(np.abs(occupancy(simpts)-occupancy(obspts)).sum())
    q=np.asarray([.1,.25,.5,.75,.9]);
    w1=float(np.mean(np.abs(np.quantile(simnearest,q)-np.quantile(nearest,q)))) if nearest else None
    boundary=sum(not (RINK_X[0]<=xy[0]<=RINK_X[1] and RINK_Y[0]<=xy[1]<=RINK_Y[1]) for xy in preds.values())
    return {"n_positions":len(err),"position_errors":err,"position_error_mean":float(np.mean(err)),
            "position_error_median":float(np.median(err)),"position_error_p90":float(np.quantile(err,.9)),
            "heading_error_mean_degrees":float(np.degrees(np.mean(heading))) if heading else None,
            "displacement_magnitude_error_mean":float(np.mean(displacement)),
            "pairwise_distance_error_mean":float(np.mean(pairerr)) if pairerr else None,
            "team_spacing_error_mean":float(np.mean(spacing)) if spacing else None,
            "occupancy_total_variation":tv,"closing_distance_quantile_w1":w1,
            "boundary_violations":int(boundary),
            "below_empirical_spacing_floor":sum(np.linalg.norm(np.asarray(preds[a])-np.asarray(preds[b]))<spacing_floor
                for i,a in enumerate(preds) for b in list(preds)[i+1:])}


def rollout_diagnostics(paths: dict, start: dict, limits: dict) -> dict:
    out={}
    for model, timeline in paths.items():
        prior={p["id"]:np.asarray(p["history"][-1])-np.asarray(p["history"][-2])
               if len(p["history"])>1 else np.zeros(2) for p in start["players"]}
        speed_viol=change_viol=turn_viol=boundary=overlap=0;changes=[];turns=[]
        prev={p["id"]:np.asarray([p["x"],p["y"]]) for p in start["players"]}
        for step in range(1,H+1):
            current={k:np.asarray(v) for k,v in timeline[step].items()}
            for pid,xy in current.items():
                v=xy-prev[pid];mag=float(np.linalg.norm(v));speed_viol+=int(mag>limits["max_displacement"])
                dv=v-prior[pid];dm=float(np.linalg.norm(dv));changes.append(dm);change_viol+=int(dm>limits["max_displacement_change"])
                if np.linalg.norm(prior[pid])>.1 and mag>.1:
                    da=abs(angle_delta(math.atan2(v[1],v[0]),math.atan2(prior[pid][1],prior[pid][0])))
                    turns.append(da);turn_viol+=int(da>limits["max_turn_radians"])
                boundary+=int(not(RINK_X[0]<=xy[0]<=RINK_X[1] and RINK_Y[0]<=xy[1]<=RINK_Y[1]))
                prior[pid]=v
            ids=list(current)
            for i,a in enumerate(ids):
                for b in ids[i+1:]: overlap+=int(np.linalg.norm(current[a]-current[b])<limits["minimum_pair_separation"])
            prev=current
        out[model]={"boundary_violations":boundary,"speed_limit_exceedances":speed_viol,
            "displacement_change_exceedances":change_viol,"turn_limit_exceedances":turn_viol,
            "mean_displacement_change_proxy":float(np.mean(changes)) if changes else None,
            "p95_displacement_change_proxy":float(np.quantile(changes,.95)) if changes else None,
            "mean_turn_change_radians":float(np.mean(turns)) if turns else None,
            "pairwise_distances_below_empirical_floor_across_rollout":overlap}
    return out


def clean_metrics(raw: dict) -> dict:
    return {k:v for k,v in raw.items() if k != "position_errors"}


def make_scenario_record(start: dict, paths: dict, puck_paths: dict, limits: dict,
                         source_manifest_sha256: str) -> dict:
    game=start["game"];scenario_id=f"{game}|{start['period']}|{start['cutoff_seq']}"
    observed_cutoff={"image_id":start["cutoff_image_id"],"seq":start["cutoff_seq"],
        "players":{p["id"]:[p["x"],p["y"]] for p in start["players"]},"puck":start.get("puck"),
        "tracking_uncertainty_category":"tracking_missingness_or_identity_conflict" in start.get("categories",[])}
    frames=[{"step":0,"observed":observed_cutoff,
        "models":{m:{"players":{p["id"]:[p["x"],p["y"]] for p in start["players"]},"puck":start.get("puck")} for m in paths}}]
    actual_by_seq={int(fr["seq"]):fr for fr in start["future_observed"]}
    for h in range(1,H+1):
        actual=actual_by_seq.get(int(start["cutoff_seq"])+h)
        frames.append({"step":h,"image_id":actual["image_id"] if actual else None,
            "observed":actual,"models":{m:{"players":paths[m][h],"puck":puck_paths[m][h]} for m in paths}})
    return {"scenario_id":scenario_id,"categories":start.get("categories",[]),
        "label":"geometry proxy; no possession or event interpretation",
        "game":game,"period":start["period"],"source_file":start["source_file"],
        "cutoff_image_id":start["cutoff_image_id"],"cutoff_seq":start["cutoff_seq"],
        "horizon_ordinal_steps":H,"random_seed":SEED,"timebase_validated":False,
        "period_one_goalie_right_team":start.get("period_one_goalie_right_team"),
        "tracking_confidence":"not supplied by source","personnel_completeness":"unknown",
        "initial_state":{"observationStep":0,"puck":start.get("puck"),
            "puckHistory":[{"x":xy[0],"y":xy[1]} for xy in (start.get("puck_history") or [])],
            "players":[{"id":p["id"],"raw_id":p["raw_id"],"jersey":p["jersey"],"team":p["team"],
                "x":p["x"],"y":p["y"],"history":[{"x":xy[0],"y":xy[1]} for xy in p["history"]]}
                for p in start["players"]]},
        "identity_conflicts_quarantined":True,"source_manifest_sha256":source_manifest_sha256,
        "model_version":FEATURE_VERSION,
        "policy_config":{"M0":"independent learned kinematics","M1":"puck and permutation-invariant player interactions",
            "M2":"M1 plus train-only ordinal constraints; 2D spacing proxy"},
        "constraints":limits,"frames":frames}


def bootstrap_deltas(by_game: dict, candidates: list[str], metric_names: list[str], games: list[str]) -> dict:
    rng=np.random.default_rng(SEED); out={}
    for left,right in (("M1","M0"),("M2","M1"),("M2","M0")):
        out[f"{left}_minus_{right}"]={}
        for metric in metric_names:
            usable=[g for g in games if by_game[g][left].get(metric) is not None and by_game[g][right].get(metric) is not None]
            if not usable:
                out[f"{left}_minus_{right}"][metric]={"equal_game_mean_delta":None,"bootstrap_95_percentile_interval":None}
                continue
            draws=rng.integers(0,len(usable),size=(BOOTSTRAPS,len(usable)))
            deltas=np.asarray([by_game[g][left][metric] - by_game[g][right][metric] for g in usable],float)
            d=np.mean(deltas[draws],axis=1)
            out[f"{left}_minus_{right}"][metric]={"equal_game_mean_delta":float(deltas.mean()),
                "bootstrap_95_percentile_interval":[float(np.quantile(d,.025)),float(np.quantile(d,.975))]}
    return out


def bootstrap_means(by_game: dict, metric_names: list[str], games: list[str], candidates: tuple[str,...]) -> dict:
    rng=np.random.default_rng(SEED+1);out={}
    for model in candidates:
        out[model]={}
        for metric in metric_names:
            usable=[g for g in games if by_game[g][model].get(metric) is not None]
            if not usable: out[model][metric]=None;continue
            vals=np.asarray([by_game[g][model][metric] for g in usable],float)
            draws=rng.integers(0,len(vals),size=(BOOTSTRAPS,len(vals)))
            means=vals[draws].mean(axis=1)
            out[model][metric]={"equal_game_mean":float(vals.mean()),"bootstrap_95_percentile_interval":[
                float(np.quantile(means,.025)),float(np.quantile(means,.975))],"games":len(usable)}
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--data-dir",type=Path,default=Path("/root/lp-research-data/nhl-multi-agent-movement-2026-10-23"))
    ap.add_argument("--output-dir",type=Path,default=Path(__file__).resolve().parent/"results")
    ap.add_argument("--gridiron-commit",default="not-recorded",help="Gridiron Physics adapter commit used for visual replay")
    args=ap.parse_args()
    git_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=Path(__file__).resolve().parents[2],text=True).strip()
    started=time.perf_counter();args.output_dir.mkdir(parents=True,exist_ok=True)
    datafile=np.load(args.data_dir/"training_windows.npz")
    data={k:datafile[k] for k in datafile.files};games=data["games"].tolist();n_games=len(games)
    x0=data["x0"].astype(float);x1=data["x1"].astype(float);pos=data["position"].astype(float);y=data["target"].astype(float)
    group=data["group"].astype(int);eligible=data["eligible"].astype(bool);keep=np.flatnonzero(eligible)
    if len(keep)<10000 or np.any(np.bincount(group[keep],minlength=n_games)<1000):
        raise RuntimeError("eligible windows fail coverage gate")
    residual=y-pos-15*x0[:,:2]
    one_by_game={g:{m:{} for m in ("M0","M1","M2")} for g in games}
    models_by_game={};limits_by_game={};one_predictions={}
    def score_one(mask,pred):
        e=np.linalg.norm(pred-y[mask],axis=1);disp=np.linalg.norm(pred-pos[mask],axis=1);td=np.linalg.norm(y[mask]-pos[mask],axis=1)
        valid=(disp>=1)&(td>=1);angles=[]
        if valid.any():
            a=pred[valid]-pos[mask][valid];b=y[mask][valid]-pos[mask][valid]
            cross=a[:,0]*b[:,1]-a[:,1]*b[:,0];dot=(a*b).sum(axis=1);angles=np.abs(np.arctan2(cross,dot))
        return {"position_error_mean":float(e.mean()),"position_error_median":float(np.median(e)),
                "position_error_p90":float(np.quantile(e,.9)),"displacement_magnitude_error_mean":float(np.abs(disp-td).mean()),
                "heading_error_mean_degrees":float(np.degrees(np.mean(angles))) if len(angles) else None,"examples":int(mask.sum())}
    for heldout in range(n_games):
        test=(group==heldout)&eligible;train=np.isin(group,[i for i in range(n_games) if i!=heldout])&eligible
        lim=thresholds(data,[i for i in range(n_games) if i!=heldout]);limits_by_game[games[heldout]]=lim
        cv=pos[test]+15*x0[test,:2]
        m0=ridge_fit(x0[train],residual[train]);m1=ridge_fit(x1[train],residual[train])
        p0=cv+ridge_predict(m0,x0[test]);p1=cv+ridge_predict(m1,x1[test])
        p2=project_pair_spacing(constrained_endpoint(p1,pos[test],x0[test],lim),
                                data["file_index"][test],data["cutoff_seq"][test],lim)
        models_by_game[games[heldout]]={
            "M0":{"mean":m0[1].tolist(),"scale":m0[2].tolist(),"coefficients":m0[0].tolist(),"feature_count":4,"featureVersion":FEATURE_VERSION},
            "M1":{"mean":m1[1].tolist(),"scale":m1[2].tolist(),"coefficients":m1[0].tolist(),"feature_count":23,"featureVersion":FEATURE_VERSION}}
        one_predictions[heldout]={"M0":p0,"M1":p1,"M2":p2,"mask":test}
        for name,pred in (("M0",p0),("M1",p1),("M2",p2)): one_by_game[games[heldout]][name]=score_one(test,pred)
        print(f"fit outer game {heldout+1}/{n_games}: {games[heldout]}",flush=True)

    # Calibrate endpoint radii on the next game, with that game excluded from the calibration fit.
    radii={}
    for i,game in enumerate(games):
        cal=(i+1)%n_games;fit=[g for g in range(n_games) if g not in (i,cal)]
        fitmask=np.isin(group,fit)&eligible;calmask=(group==cal)&eligible
        lim=thresholds(data,fit);cvcal=pos[calmask]+15*x0[calmask,:2]
        r0=ridge_fit(x0[fitmask],residual[fitmask]);r1=ridge_fit(x1[fitmask],residual[fitmask])
        q0=cvcal+ridge_predict(r0,x0[calmask]);q1=cvcal+ridge_predict(r1,x1[calmask])
        q2=project_pair_spacing(constrained_endpoint(q1,pos[calmask],x0[calmask],lim),
                                data["file_index"][calmask],data["cutoff_seq"][calmask],lim)
        radii[game]={"M0":q90(np.linalg.norm(q0-y[calmask],axis=1)),
                     "M1":q90(np.linalg.norm(q1-y[calmask],axis=1)),
                     "M2":q90(np.linalg.norm(q2-y[calmask],axis=1))}

    overall_one={m:{k+"_equal_game_mean":float(np.mean([one_by_game[g][m][k] for g in games]))
                    for k in ("position_error_mean","position_error_median","position_error_p90",
                              "displacement_magnitude_error_mean","heading_error_mean_degrees")} for m in ("M0","M1","M2")}
    one_intervals=bootstrap_deltas(one_by_game,["M0","M1","M2"],
        ["position_error_mean","position_error_median","position_error_p90","displacement_magnitude_error_mean","heading_error_mean_degrees"],games)
    with gzip.open(args.data_dir/"rollout_starts.json.gz","rt",encoding="utf-8") as f: starts=json.load(f)
    startrows=starts["starts"]
    if len(startrows)!=20*n_games: raise RuntimeError(f"expected 20 starts/game; got {len(startrows)}")
    extraction=json.load(open(args.data_dir/"extraction_manifest.json"))
    source_manifest_sha256=extraction["source_release"]["manifest_sha256"]
    samples=[];scenario_cache={}
    for si,start in enumerate(startrows):
        game=start["game"];gi=games.index(game);mods=models_by_game[game];lim=limits_by_game[game]
        paths,puck_paths,cc=rollout(start,mods["M0"],mods["M1"],lim)
        diagnostics=rollout_diagnostics(paths,start,lim)
        actual_by_seq={int(fr["seq"]):fr for fr in start["future_observed"]}
        initial={p["id"]:[p["x"],p["y"]] for p in start["players"]}
        rows=[]
        for horizon in (1,5,15,30,45):
            seq=int(start["cutoff_seq"])+horizon;actual=actual_by_seq.get(seq)
            for name in ("M0","M1","M2"):
                pred=paths[name].get(horizon,{})
                metric=frame_metrics(pred,actual or {"players":{}},start,lim["minimum_pair_separation"])
                metric.update({"scenario_index":si,"game":game,"model":name,"horizon":horizon,
                               "target_available":actual is not None,"target_records":len(actual["players"]) if actual else 0,
                               "generated_players":len(pred),
                               "target_coverage":metric["n_positions"]/max(1,len(start["players"])),
                               "missing_position_labels":max(0,len(start["players"])-metric["n_positions"]),
                               "target_identity_conflict_present":bool(actual and actual.get("conflicted_present")),
                               "endpoint_radius_90":radii[game][name],
                               "endpoint_radius_coverage_diagnostic":float(np.mean(np.asarray(metric.get("position_errors",[]))<=radii[game][name]))
                                    if metric.get("position_errors") else None})
                rows.append(metric)
        samples.append({"game":game,"scenario_index":si,"metrics":rows,"constraints":cc,"trajectory_diagnostics":diagnostics,
                        "target_sequence_count":len(actual_by_seq),"initial_players":len(start["players"])})
        if si%10==9: print(f"rolled {si+1}/{len(startrows)} shared starts",flush=True)

        scenario_id=f"{game}|{start['period']}|{start['cutoff_seq']}"
        scenario_cache[scenario_id]=make_scenario_record(start,paths,puck_paths,lim,source_manifest_sha256)

    # Keep the earliest deterministic pre-cutoff example for each frozen geometry/quality category.
    for category,start in starts.get("category_examples",{}).items():
        scenario_id=f"{start['game']}|{start['period']}|{start['cutoff_seq']}"
        if scenario_id in scenario_cache: continue
        game=start["game"];limits=limits_by_game[game];models=models_by_game[game]
        paths,pucks,_=rollout(start,models["M0"],models["M1"],limits)
        scenario_cache[scenario_id]=make_scenario_record(start,paths,pucks,limits,source_manifest_sha256)

    # Score rollouts at equal game weight and bootstrap paired differences by whole game.
    horizons=(1,5,15,30,45);roll_by_game={g:{} for g in games};roll_overall={}
    roll_metrics=("position_error_mean","position_error_median","position_error_p90","heading_error_mean_degrees",
                  "displacement_magnitude_error_mean","pairwise_distance_error_mean","team_spacing_error_mean",
                  "occupancy_total_variation","closing_distance_quantile_w1",
                  "boundary_violations","below_empirical_spacing_floor",
                  "endpoint_radius_coverage_diagnostic","target_coverage","missing_position_labels")
    bootstrap_roll={};roll_mean_intervals={}
    for h in horizons:
        roll_by_game={g:{m:{} for m in ("M0","M1","M2")} for g in games}
        for game in games:
            sr=[s for s in samples if s["game"]==game]
            for model in ("M0","M1","M2"):
                mr=[r for s in sr for r in s["metrics"] if r["model"]==model and r["horizon"]==h and r["position_error_mean"] is not None]
                vals={k:[] for k in roll_metrics}
                # Equal weight per start, then equal game weight in final summary.
                for s in sr:
                    match=next((r for r in s["metrics"] if r["model"]==model and r["horizon"]==h),None)
                    if match and match["position_error_mean"] is not None:
                        for k in roll_metrics:
                            if match.get(k) is not None: vals[k].append(match[k])
                roll_by_game[game][model]={k:(float(np.mean(v)) if v else None) for k,v in vals.items()}
        roll_overall[str(h)]={m:{k+"_equal_game_mean":float(np.mean([roll_by_game[g][m][k] for g in games if roll_by_game[g][m][k] is not None]))
                                      for k in roll_metrics} for m in ("M0","M1","M2")}
        present=[g for g in games if all(roll_by_game[g][m]["position_error_mean"] is not None for m in ("M0","M1","M2"))]
        bootstrap_roll[str(h)]=bootstrap_deltas(roll_by_game,["M0","M1","M2"],
             [k for k in roll_metrics if k in roll_by_game[present[0]]["M0"]],present) if present else {}
        roll_mean_intervals[str(h)]=bootstrap_means(roll_by_game,["position_error_mean","position_error_median","position_error_p90",
            "heading_error_mean_degrees","displacement_magnitude_error_mean","pairwise_distance_error_mean",
            "team_spacing_error_mean","occupancy_total_variation","closing_distance_quantile_w1",
            "endpoint_radius_coverage_diagnostic","target_coverage","missing_position_labels",
            "boundary_violations","below_empirical_spacing_floor"],games,("M0","M1","M2"))

    # Add model-specific uncertainty coverage to endpoint metrics using the frozen next-game calibration.
    for game in games:
        for model in ("M0","M1","M2"):
            e=np.linalg.norm(one_predictions[games.index(game)][model]-y[one_predictions[games.index(game)]["mask"]],axis=1)
            one_by_game[game][model]["calibrated_radius_90"] = radii[game][model]
            one_by_game[game][model]["calibrated_coverage"] = float(np.mean(e <= radii[game][model]))
    one_mean_intervals=bootstrap_means(one_by_game,["position_error_mean","position_error_median","position_error_p90",
        "displacement_magnitude_error_mean","heading_error_mean_degrees","calibrated_coverage"],games,("M0","M1","M2"))

    serialized_models={"protocol":"docs/research/NHL-MULTI-AGENT-MOVEMENT-PROTOCOL-2026-10-23.md",
        "feature_version":FEATURE_VERSION,"seed":SEED,"folds":models_by_game,"constraints":limits_by_game,
        "calibration_radii_90":radii,"timebase":"ordinal Image Id increments; no seconds conversion"}
    models_path=args.output_dir/f"fold_models-{git_commit[:12]}.json"
    with models_path.open("x", encoding="utf-8") as f:
        json.dump(serialized_models, f, indent=2, default=json_default, allow_nan=False)
        f.write("\n")
    visual={"archive_version":"nhl-movement-visual-v0.1","legendarypicks_git_commit":git_commit,
            "gridiron_physics_git_commit":args.gridiron_commit,
            "source_hashes":json.load(open(args.data_dir/"extraction_manifest.json"))["artifacts"],
            "fold_models":models_by_game,"fold_constraints":limits_by_game,
            "scenarios":scenario_cache}
    archive_path=args.output_dir/f"scenario_archive-{git_commit[:12]}.json.gz"
    if archive_path.exists(): raise FileExistsError(f"refusing to overwrite versioned archive {archive_path}")
    with gzip.open(archive_path,"xt",encoding="utf-8",compresslevel=6) as f:
        json.dump(visual, f, separators=(",",":"), default=json_default, allow_nan=False)
    samples_compact=[{**s,"metrics":[clean_metrics(r) for r in s["metrics"]]} for s in samples]
    extraction=json.load(open(args.data_dir/"extraction_manifest.json"))
    scores={"study":"NHL multi-agent movement v0.1, ten-game inspected development sample",
        "protocol":"docs/research/NHL-MULTI-AGENT-MOVEMENT-PROTOCOL-2026-10-23.md",
        "git_commit":git_commit,"source_manifest_sha256":extraction["source_release"]["manifest_sha256"],
        "games":games,"sample":{"eligible_one_step_windows":int(len(keep)),"raw_windows":int(len(eligible)),
            "excluded_conflicted_windows":int((~eligible).sum()),"rollout_starts":len(startrows),"starts_per_game":20,
            "normalized_observation_groups":extraction["counts"]["normalized_observation_groups"],
            "normalized_player_rows":extraction["counts"]["normalized_player_rows"],
            "identity_conflicts":extraction["counts"]["conflicted_track_period_ids"],
            "missing_xy_rows":extraction["counts"]["rows_missing_or_invalid_xy"]},
        "one_step_plus_15_ordinal_increments":{"by_game":one_by_game,"equal_game_mean":overall_one,
            "paired_game_bootstrap":one_intervals,"absolute_game_bootstrap":one_mean_intervals},
        "rollout_by_horizon_ordinal_steps":roll_overall,"rollout_by_game":roll_by_game,
        "rollout_paired_game_bootstrap":bootstrap_roll,"rollout_absolute_game_bootstrap":roll_mean_intervals,
        "rollout_samples":samples_compact,
        "scenario_categories_available":sorted({c for s in startrows for c in s.get("categories",[])} |
                                                set(starts.get("category_examples",{}))),
        "scenario_archive":str(archive_path),"versioned_visual_scenario_count":len(scenario_cache),
        "fold_models":str(models_path),"independent_adoption_test":False,
        "runtime_seconds":round(time.perf_counter()-started,3),
        "interpretation":"All results are grouped within-sample development comparisons. No independent-game validation; no timed physics or collision claim."}
    scorepath=args.output_dir/f"movement_comparison-{git_commit[:12]}.json"
    with scorepath.open("x", encoding="utf-8") as f:
        json.dump(scores, f, indent=2, sort_keys=True, default=json_default, allow_nan=False)
        f.write("\n")
    print(json.dumps({"one_step_equal_game_mean":overall_one,"one_step_paired_intervals":one_intervals,
        "rollout_by_horizon":roll_overall,"scenario_categories":sorted(scenario_cache),
        "runtime_seconds":scores["runtime_seconds"],"output":str(scorepath)},indent=2,
        default=json_default,allow_nan=False),flush=True)


if __name__=="__main__":main()
