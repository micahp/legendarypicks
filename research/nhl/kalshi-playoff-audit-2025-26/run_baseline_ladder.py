#!/usr/bin/env python3
"""Fit preregistered NHL baselines, evaluate held-out seasons, then Kalshi separately."""
import csv
import hashlib
import json
import math
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
CANONICAL = HERE / "canonical_games_v1_7cd2fc9a6e84470c.csv"
FEATURES = HERE / "pregame_rolling_features_v1_62dcceb77085bc59.csv"
CROSSWALK = HERE / "game_crosswalk.csv"
QUOTES = HERE / "pregame_quotes.csv"
PREREG = HERE / "backtest_preregistration_v1.md"
TRAIN_END = 2017
VALIDATION = range(2018, 2022)
LOCKED_TEST = range(2022, 2025)
FINAL_SEASON = 2025
ELO_K = (10, 20, 30, 40)
ELO_HFA = (35, 65, 100)
POISSON_ALPHA = (0.01, 0.1, 1.0, 10.0)
LOGIT_C = (0.01, 0.1, 1.0, 10.0, 100.0)
RNG = np.random.default_rng(20261014)

TEAM_ID = {"PHX":"ARI", "T.B":"TBL", "N.J":"NJD", "L.A":"LAK", "S.J":"SJS",
           "ATL":"WPG"}


def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b""): h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with open(path,newline="") as f: return list(csv.DictReader(f))


def f(row,key):
    v=row.get(key," ")
    if v in (None,""," "): return None
    try: return float(v)
    except ValueError: return None


def team_key(code): return TEAM_ID.get(code,code)


def lograte(value): return math.log(max(float(value),0.05))


def logit(p):
    p=min(max(float(p),1e-6),1-1e-6)
    return math.log(p/(1-p))


def expit(x): return 1/(1+math.exp(-max(-35,min(35,float(x)))))


def poisson_logpmf(y, mu):
    mu=max(1e-9,float(mu)); y=int(y)
    return y*math.log(mu)-mu-math.lgamma(y+1)


def poisson_win_prob(home_mu, away_mu, shootout_home):
    # Tail above 20 goals is negligible for the fitted NHL scoring means.
    vals=np.arange(21)
    def pmf(mu):
        mu=max(1e-9,float(mu))
        x=np.exp(vals*math.log(mu)-mu-np.array([math.lgamma(int(v)+1) for v in vals]))
        return x/x.sum()
    h,a=pmf(home_mu),pmf(away_mu)
    p_home=float(sum(h[i]*a[:i].sum() for i in range(21)))
    p_tie=float(np.dot(h,a))
    return min(1-1e-8,max(1e-8,p_home+p_tie*shootout_home))


def calibration_metrics(y,p):
    y=np.asarray(y,dtype=float); p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
    brier=float(np.mean((p-y)**2))
    ll=float(np.mean(-(y*np.log(p)+(1-y)*np.log(1-p))))
    bins=[]
    for lo in np.linspace(0,0.9,10):
        hi=lo+0.1
        mask=(p>=lo)&(p<(hi if hi<1 else 1.000001))
        if mask.any(): bins.append((int(mask.sum()),float(p[mask].mean()),float(y[mask].mean())))
    ece=sum(n*abs(pred-obs) for n,pred,obs in bins)/len(y) if bins else float("nan")
    z=np.log(p/(1-p)).reshape(-1,1)
    try:
        cal=LogisticRegression(C=1e6,solver="lbfgs",max_iter=1000).fit(z,y.astype(int))
        intercept=float(cal.intercept_[0]); slope=float(cal.coef_[0,0])
    except Exception:
        intercept=slope=float("nan")
    return {"n":len(y),"brier":brier,"log_loss":ll,"calibration_intercept":intercept,
            "calibration_slope":slope,"ece_10_bins":float(ece)}


def goal_metrics(rows,home_mu,away_mu):
    hg=np.array([int(r["home_goals_model_target"]) for r in rows],dtype=float)
    ag=np.array([int(r["away_goals_model_target"]) for r in rows],dtype=float)
    hm=np.asarray(home_mu,dtype=float); am=np.asarray(away_mu,dtype=float)
    per_team_abs=(np.abs(hg-hm)+np.abs(ag-am))/2
    per_team_sq=((hg-hm)**2+(ag-am)**2)/2
    total_abs=np.abs((hg+ag)-(hm+am))
    nll=np.array([-poisson_logpmf(y,m) for y,m in zip(hg,hm)])+np.array([-poisson_logpmf(y,m) for y,m in zip(ag,am)])
    return {"n":len(rows),"goals_mae_per_team":float(per_team_abs.mean()),
            "goals_rmse_per_team":float(math.sqrt(per_team_sq.mean())),
            "total_goals_mae":float(total_abs.mean()),"joint_poisson_nll":float(nll.mean())}, per_team_abs, nll


def paired_bootstrap_delta(a,b,iterations=4000):
    # Positive delta means model A has greater loss than model B.
    a=np.asarray(a,dtype=float); b=np.asarray(b,dtype=float)
    d=a-b; n=len(d)
    samples=np.empty(iterations)
    for i in range(iterations): samples[i]=RNG.choice(d,size=n,replace=True).mean()
    return {"delta_a_minus_b":float(d.mean()),"ci95_low":float(np.quantile(samples,.025)),
            "ci95_high":float(np.quantile(samples,.975)),"n_games":n}


def elo_predictions(games,k,hfa):
    ratings=defaultdict(lambda:1500.0); out={}
    by_date=defaultdict(list)
    for r in games: by_date[r["game_date"]].append(r)
    for date in sorted(by_date):
        updates=[]
        for r in by_date[date]:
            gid=int(r["game_id"]); home,away=team_key(r["home_team"]),team_key(r["away_team"])
            venue=0.0 if r["neutral_site"].lower()=="true" else hfa
            rh,ra=ratings[home],ratings[away]
            expected=1/(1+10**(-((rh-ra+venue)/400)))
            out[gid]={"prob":expected,"home_elo":rh,"away_elo":ra,"diff":(rh-ra)/400.0,"home_venue":float(venue>0)}
            updates.append((home,away,float(int(r["official_home_winner"])-expected)))
        for home,away,residual in updates:
            change=k*residual
            ratings[home]+=change; ratings[away]-=change
    return out


def recent_form(games):
    history=defaultdict(list); out={}
    for r in games:
        gid=int(r["game_id"]); h,a=team_key(r["home_team"]),team_key(r["away_team"])
        def form(team):
            prev=[x for x in history[team] if x["date"]<r["game_date"]][-10:]
            if len(prev)<5:return None
            return (sum(x["win"] for x in prev)/len(prev),
                    sum(x["gf"]-x["ga"] for x in prev)/len(prev))
        hf,af=form(h),form(a)
        out[gid]={"home_win10":hf[0] if hf else None,"home_gd10":hf[1] if hf else None,
                  "away_win10":af[0] if af else None,"away_gd10":af[1] if af else None}
        hg=int(r["home_goals_model_target"]); ag=int(r["away_goals_model_target"])
        hw=int(r["official_home_winner"])
        history[h].append({"date":r["game_date"],"win":hw,"gf":hg,"ga":ag})
        history[a].append({"date":r["game_date"],"win":1-hw,"gf":ag,"ga":hg})
    return out


def load_data():
    canon=read_csv(CANONICAL); feats=read_csv(FEATURES)
    assert len(canon)==23222 and len(feats)==23222
    feature_by_id={int(x["game_id"]):x for x in feats}
    games=[]
    for c in canon:
        gid=int(c["game_id"]); x=feature_by_id[gid]
        if x["required_features_complete"].lower()!="true": continue
        # These hashes are asserted in the preregistered protocol's source report.
        z={**c,**x}
        z["game_id"]=gid; z["season"]=int(c["season"])
        z["official_home_winner"]=int(c["official_home_winner"])
        z["home_goals_model_target"]=int(c["home_goals_model_target"])
        z["away_goals_model_target"]=int(c["away_goals_model_target"])
        z["neutral_site"]=c["neutral_site"]
        games.append(z)
    games.sort(key=lambda r:(r["game_date"],r["start_time_utc"],r["game_id"]))
    forms=recent_form(games)
    for r in games:r.update(forms[r["game_id"]])
    return games


def fit_elo_grid(games):
    best=None; candidates=[]; predictions={}
    y=np.array([int(r["official_home_winner"]) for r in games if r["season"] in VALIDATION])
    val_ids=[r["game_id"] for r in games if r["season"] in VALIDATION]
    for k in ELO_K:
        for hfa in ELO_HFA:
            pred=elo_predictions(games,k,hfa)
            p=np.array([pred[g]["prob"] for g in val_ids])
            m=calibration_metrics(y,p)
            candidates.append({"k":k,"home_ice_elo":hfa,**m})
            key=(m["brier"],m["log_loss"],k,hfa)
            if best is None or key<best[0]:best=(key,k,hfa)
            predictions[(k,hfa)]=pred
    return best[1],best[2],predictions[(best[1],best[2])],candidates


def make_side_dataset(rows,model,elo_by_id):
    X=[]; y=[]; keys=[]
    for r in rows:
        if model=="goals":
            h_off=lograte(r["home_rolling10_goals_for"]); a_def=lograte(r["away_rolling10_goals_against"])
            a_off=lograte(r["away_rolling10_goals_for"]); h_def=lograte(r["home_rolling10_goals_against"])
            X.extend([[1.0,h_off,a_def],[0.0,a_off,h_def]])
        elif model=="xg":
            h_off=lograte(r["home_rolling10_5v5_score_venue_xgf"]); a_def=lograte(r["away_rolling10_5v5_score_venue_xga"])
            a_off=lograte(r["away_rolling10_5v5_score_venue_xgf"]); h_def=lograte(r["home_rolling10_5v5_score_venue_xga"])
            X.extend([[1.0,h_off,a_def],[0.0,a_off,h_def]])
        elif model=="combined":
            X.extend([[1.0,lograte(r["home_rolling10_goals_for"]),lograte(r["away_rolling10_goals_against"]),
                       lograte(r["home_rolling10_5v5_score_venue_xgf"]),lograte(r["away_rolling10_5v5_score_venue_xga"])],
                      [0.0,lograte(r["away_rolling10_goals_for"]),lograte(r["home_rolling10_goals_against"]),
                       lograte(r["away_rolling10_5v5_score_venue_xgf"]),lograte(r["home_rolling10_5v5_score_venue_xga"]) ]])
        elif model=="elo":
            e=elo_by_id[r["game_id"]]; d=e["diff"]
            X.extend([[e["home_venue"],d],[0.0,-d]])
        y.extend([r["home_goals_model_target"],r["away_goals_model_target"]])
        keys.extend([(r["game_id"],"home"),(r["game_id"],"away")])
    return np.asarray(X,dtype=float),np.asarray(y,dtype=float),keys


def fit_poisson_for_validation(games,model,elo_by_id=None):
    train=[r for r in games if r["season"]<=TRAIN_END]
    val=[r for r in games if r["season"] in VALIDATION]
    xtr,ytr,_=make_side_dataset(train,model,elo_by_id or {})
    xva,yva,keys=make_side_dataset(val,model,elo_by_id or {})
    choices=[]
    for alpha in POISSON_ALPHA:
        mdl=PoissonRegressor(alpha=alpha,max_iter=500,tol=1e-9).fit(xtr,ytr)
        pred=np.maximum(mdl.predict(xva),1e-8)
        nll=float(np.mean([-poisson_logpmf(y,m) for y,m in zip(yva,pred)]))
        choices.append({"alpha":alpha,"validation_team_goal_nll":nll,"n_team_observations":len(yva)})
    best=min(choices,key=lambda x:(x["validation_team_goal_nll"],x["alpha"]))
    return best["alpha"],choices


def fit_recent_c(games):
    train=[r for r in games if r["season"]<=TRAIN_END]
    val=[r for r in games if r["season"] in VALIDATION]
    train=[r for r in train if r["home_win10"] is not None and r["away_win10"] is not None]
    valid=[r for r in val if r["home_win10"] is not None and r["away_win10"] is not None]
    Xtr=recent_matrix(train); ytr=np.array([r["official_home_winner"] for r in train])
    base=float(np.mean([r["official_home_winner"] for r in [g for g in games if g["season"]<=TRAIN_END]]))
    out=[]
    for c in LOGIT_C:
        mdl=make_pipeline(StandardScaler(),LogisticRegression(C=c,max_iter=2000,solver="lbfgs"))
        mdl.fit(Xtr,ytr); p=np.full(len(val),base,dtype=float)
        positions=[i for i,r in enumerate(val) if r["home_win10"] is not None and r["away_win10"] is not None]
        if positions:p[positions]=mdl.predict_proba(recent_matrix(valid))[:,1]
        yv=np.array([r["official_home_winner"] for r in val])
        out.append({"C":c,**calibration_metrics(yv,p)})
    return min(out,key=lambda x:(x["brier"],x["log_loss"],x["C"])),out


def recent_matrix(rows):
    return np.array([[r["home_win10"],r["away_win10"],r["home_gd10"],r["away_gd10"],
        float(r["neutral_site"].lower()!="true"),float((f(r,"home_days_rest") or 0)-(f(r,"away_days_rest") or 0))] for r in rows])


def fit_recent_final(games,c,through=2021):
    tr=[r for r in games if r["season"]<=through and r["home_win10"] is not None and r["away_win10"] is not None]
    mdl=make_pipeline(StandardScaler(),LogisticRegression(C=c,max_iter=2000,solver="lbfgs"))
    mdl.fit(recent_matrix(tr),np.array([r["official_home_winner"] for r in tr]))
    return mdl


def fit_goal_models(games,elo_by_id,alphas,through):
    train=[r for r in games if r["season"]<=through]
    fitted={}
    for model in ("elo","goals","xg","combined"):
        X,y,_=make_side_dataset(train,model,elo_by_id)
        mdl=PoissonRegressor(alpha=alphas[model],max_iter=500,tol=1e-9).fit(X,y)
        fitted[model]=mdl
    tie_rows=[r for r in train if r["home_goals_model_target"]==r["away_goals_model_target"]]
    so_home=(sum(r["official_home_winner"] for r in tie_rows)/len(tie_rows)) if tie_rows else .5
    mean_h=np.mean([r["home_goals_model_target"] for r in train]); mean_a=np.mean([r["away_goals_model_target"] for r in train])
    home_rate=np.mean([r["official_home_winner"] for r in train])
    return fitted,float(so_home),float(mean_h),float(mean_a),float(home_rate)


def predict_goals(model,rows,mdl,elo_by_id):
    X,_,keys=make_side_dataset(rows,model,elo_by_id)
    values=np.maximum(mdl.predict(X),1e-8)
    out={}
    for (gid,side),mu in zip(keys,values): out.setdefault(gid,{})[side]=float(mu)
    return out


def make_predictions(rows,fit,elo_pred,elo_score_pred,recent_model,so_home,mean_h,mean_a,home_rate):
    preds=[]
    score_means={name:predict_goals(name,rows,fit[name],elo_score_pred) for name in ("elo","goals","xg","combined")}
    recent_valid=[i for i,r in enumerate(rows) if r["home_win10"] is not None and r["away_win10"] is not None
                  and r["home_gd10"] is not None and r["away_gd10"] is not None]
    precent=np.full(len(rows),home_rate,dtype=float)
    if recent_valid:
        precent[recent_valid]=recent_model.predict_proba(recent_matrix([rows[i] for i in recent_valid]))[:,1]
    for i,r in enumerate(rows):
        gid=r["game_id"]
        ph={"B0":.5,"B1":home_rate,"B2":float(precent[i]),"B3":elo_pred[gid]["prob"]}
        scores={"B0":(mean_h,mean_a),"B1":(mean_h,mean_a)}
        for name,model in (("B3","elo"),("B4","goals"),("B5","xg"),("B6","combined")):
            m=score_means[model][gid]; scores[name]=(m["home"],m["away"])
        for name in ("B4","B5","B6"):
            hm,am=scores[name]
            ph[name]=poisson_win_prob(hm,am,so_home)
        row={"game_id":gid,"season":r["season"],"game_date":r["game_date"],"game_type":r["game_type"],
             "home_team":r["home_team"],"away_team":r["away_team"],"official_home_winner":r["official_home_winner"],
             "home_goals_model_target":r["home_goals_model_target"],"away_goals_model_target":r["away_goals_model_target"],
             "last_period_type":r["last_period_type"],"split":"validation" if r["season"] in VALIDATION else "holdout"}
        for name,p in ph.items(): row[f"{name}_home_win_probability"]=p
        for name,(hm,am) in scores.items(): row[f"{name}_home_expected_goals"]=hm;row[f"{name}_away_expected_goals"]=am
        row["elo_rating_diff_pre_game"]=elo_pred[gid]["home_elo"]-elo_pred[gid]["away_elo"]
        preds.append(row)
    return preds


def metric_tables(preds):
    metrics=[]; errors={}
    for season in sorted(set(r["season"] for r in preds)):
        rows=[r for r in preds if r["season"]==season]
        y=[r["official_home_winner"] for r in rows]
        for model in ("B0","B1","B2","B3","B4","B5","B6"):
            cal=calibration_metrics(y,[r[f"{model}_home_win_probability"] for r in rows])
            metrics.append({"season":season,"split":rows[0]["split"],"model":model,"target":"moneyline",**cal})
        for model in ("B0","B1","B3","B4","B5","B6"):
            gm,abs_err,nll=goal_metrics(rows,[r[f"{model}_home_expected_goals"] for r in rows],
                [r[f"{model}_away_expected_goals"] for r in rows])
            metrics.append({"season":season,"split":rows[0]["split"],"model":model,"target":"goals",**gm})
            errors[(season,model)]=(abs_err,nll)
    return metrics,errors


def market_comparison(preds):
    # Market is loaded only after statistical specs and predictions are locked.
    cross={int(r["game_id"]):r for r in read_csv(CROSSWALK)}
    quotes=read_csv(QUOTES); sides=defaultdict(dict)
    for q in quotes:
        gid=int(q["game_id"]); team=team_key(q["market_side_team"])
        mid=(float(q["yes_bid"])+float(q["yes_ask"]))/2
        sides[gid][team]=mid
    byid={r["game_id"]:r for r in preds}; matched=[]
    for gid,cr in cross.items():
        if cr["coverage_status"]!="matched" or gid not in byid:continue
        pr=byid[gid]; h=team_key(pr["home_team"]);a=team_key(pr["away_team"])
        if h not in sides[gid] or a not in sides[gid]: raise RuntimeError(f"Missing Kalshi side for {gid}")
        hm=sides[gid][h];am=sides[gid][a]
        market_home=hm/(hm+am)
        matched.append({**pr,"kalshi_home_probability":market_home,"kalshi_home_mid_raw":hm,
                        "kalshi_away_mid_raw":am,"kalshi_event_ticker":cr["kalshi_event_ticker"]})
    if len(matched)!=80:raise RuntimeError(f"Expected 80 Kalshi games, joined {len(matched)}")
    result=[]
    y=[r["official_home_winner"] for r in matched]
    for model in ("B0","B1","B2","B3","B4","B5","B6"):
        result.append({"comparison":"statistical_model","model":model,**calibration_metrics(y,[r[f"{model}_home_win_probability"] for r in matched])})
    result.append({"comparison":"market_midpoint","model":"Kalshi normalized YES midpoints",**calibration_metrics(y,[r["kalshi_home_probability"] for r in matched])})
    return matched,result


def write_csv(path,rows):
    if not rows:return
    cols=list(dict.fromkeys(k for r in rows for k in r))
    with open(path,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore");w.writeheader();w.writerows(rows)


def main():
    prereg_sha=sha(PREREG)
    if sha(CANONICAL)!="7cd2fc9a6e84470c177b704aa56ba328ad67522698244ce1f182ddcb9e439f52":raise RuntimeError("Canonical source hash changed")
    if sha(FEATURES)!="62dcceb77085bc59fcad3ca9a0a981e0e462909cd09815cde98e45b7e9caf458":raise RuntimeError("Feature source hash changed")
    games=load_data()
    print(f"eligible game rows={len(games)}; preregistration sha256={prereg_sha}",flush=True)
    elo_k,elo_hfa,elo_valpred,elo_grid=fit_elo_grid(games)
    print(f"validation-selected Elo K={elo_k}, home-ice={elo_hfa}",flush=True)
    recent_best,recent_grid=fit_recent_c(games)
    alphas={};alpha_grids={}
    for model in ("elo","goals","xg","combined"):
        alphas[model],alpha_grids[model]=fit_poisson_for_validation(games,model,elo_valpred)
        print(f"validation-selected {model} Poisson alpha={alphas[model]}",flush=True)

    initial_fit={}; initial_so=None
    for model in ("elo","goals","xg","combined"):
        X,y,_=make_side_dataset([r for r in games if r["season"]<=TRAIN_END],model,elo_valpred)
        initial_fit[model]=PoissonRegressor(alpha=alphas[model],max_iter=500,tol=1e-9).fit(X,y)
    tie_train=[r for r in games if r["season"]<=TRAIN_END and r["home_goals_model_target"]==r["away_goals_model_target"]]
    initial_so=sum(r["official_home_winner"] for r in tie_train)/len(tie_train)
    base_train=[r for r in games if r["season"]<=TRAIN_END]
    initial_mh=np.mean([r["home_goals_model_target"] for r in base_train]);initial_ma=np.mean([r["away_goals_model_target"] for r in base_train])
    initial_recent=fit_recent_final(games,recent_best["C"],TRAIN_END)
    initial_home_rate=np.mean([r["official_home_winner"] for r in base_train])
    validation=[r for r in games if r["season"] in VALIDATION]
    valpred=make_predictions(validation,initial_fit,elo_valpred,elo_valpred,initial_recent,initial_so,initial_mh,initial_ma,initial_home_rate)

    # Lock statistical model-selection winners using validation only.
    val_metrics,_=metric_tables(valpred)
    val_win=[x for x in val_metrics if x["target"]=="moneyline" and x["model"] in ("B2","B3","B4","B5","B6")]
    best_win=min(val_win,key=lambda x:(x["brier"],x["log_loss"],{"B3":0,"B4":1,"B5":2,"B6":3,"B2":4}[x["model"]]))["model"]
    val_goal=[x for x in val_metrics if x["target"]=="goals" and x["model"] in ("B3","B4","B5","B6")]
    best_goal=min(val_goal,key=lambda x:(x["joint_poisson_nll"],{"B3":0,"B4":1,"B5":2,"B6":3}[x["model"]]))["model"]
    print(f"locked by validation: winner={best_win}, goal distribution={best_goal}",flush=True)

    # Freeze hyperparameters, refit GLM coefficients through 2021; produce 2022-25 once.
    elo_all=elo_predictions(games,elo_k,elo_hfa)
    final_fit,final_so,final_mh,final_ma,final_home_rate=fit_goal_models(games,elo_all,alphas,2021)
    recent_final=fit_recent_final(games,recent_best["C"])
    holdout=[r for r in games if r["season"]>=2022]
    holdpred=make_predictions(holdout,final_fit,elo_all,elo_all,recent_final,final_so,final_mh,final_ma,final_home_rate)
    allpred=valpred+holdpred
    metrics,errors=metric_tables(allpred)

    # Paired score-loss comparisons: positive is loss(model A) - loss(model B).
    paired=[]
    for label,rows in (("locked_test_2022_2024",[r for r in holdpred if r["season"] in LOCKED_TEST]),
                       ("final_2025_26",[r for r in holdpred if r["season"]==FINAL_SEASON])):
        for a,b in (("B5","B4"),("B5","B3"),("B6","B4")):
            abs_a=np.array([(abs(int(r["home_goals_model_target"])-r[f"{a}_home_expected_goals"])+abs(int(r["away_goals_model_target"])-r[f"{a}_away_expected_goals"]))/2 for r in rows])
            abs_b=np.array([(abs(int(r["home_goals_model_target"])-r[f"{b}_home_expected_goals"])+abs(int(r["away_goals_model_target"])-r[f"{b}_away_expected_goals"]))/2 for r in rows])
            nll_a=np.array([-poisson_logpmf(r["home_goals_model_target"],r[f"{a}_home_expected_goals"])-poisson_logpmf(r["away_goals_model_target"],r[f"{a}_away_expected_goals"]) for r in rows])
            nll_b=np.array([-poisson_logpmf(r["home_goals_model_target"],r[f"{b}_home_expected_goals"])-poisson_logpmf(r["away_goals_model_target"],r[f"{b}_away_expected_goals"]) for r in rows])
            paired.append({"sample":label,"model_a":a,"model_b":b,"metric":"per_game_team_goals_mae",
                           **paired_bootstrap_delta(abs_a,abs_b)})
            paired.append({"sample":label,"model_a":a,"model_b":b,"metric":"joint_goal_nll",
                           **paired_bootstrap_delta(nll_a,nll_b)})
    # Paired moneyline Brier differences for locked test and untouched season.
    for label,rows in (("locked_test_2022_2024",[r for r in holdpred if r["season"] in LOCKED_TEST]),
                       ("final_2025_26",[r for r in holdpred if r["season"]==FINAL_SEASON])):
        for a,b in (("B5","B3"),("B5","B4"),("B6","B4")):
            y=np.array([r["official_home_winner"] for r in rows])
            la=(np.array([r[f"{a}_home_win_probability"] for r in rows])-y)**2
            lb=(np.array([r[f"{b}_home_win_probability"] for r in rows])-y)**2
            paired.append({"sample":label,"model_a":a,"model_b":b,"metric":"moneyline_brier",**paired_bootstrap_delta(la,lb)})

    # Statistical set is now locked. Only now read Kalshi quotes for the separate playoff benchmark.
    final_season_predictions=[r for r in holdpred if r["season"]==FINAL_SEASON]
    kalshi_rows,kalshi_metrics=market_comparison(final_season_predictions)
    best_probs=best_win
    mp=[r["official_home_winner"] for r in kalshi_rows]
    chosen=calibration_metrics(mp,[r[f"{best_probs}_home_win_probability"] for r in kalshi_rows])
    market=calibration_metrics(mp,[r["kalshi_home_probability"] for r in kalshi_rows])
    model_losses=(np.array([r[f"{best_probs}_home_win_probability"] for r in kalshi_rows])-np.array(mp))**2
    market_losses=(np.array([r["kalshi_home_probability"] for r in kalshi_rows])-np.array(mp))**2
    kalshi_delta=paired_bootstrap_delta(model_losses,market_losses)

    # Write reproducible artifacts.
    write_csv(HERE/"baseline_predictions_validation.csv",valpred)
    write_csv(HERE/"baseline_predictions_holdout_2022_2025.csv",holdpred)
    write_csv(HERE/"baseline_metrics_by_season.csv",metrics)
    write_csv(HERE/"baseline_paired_differences.csv",paired)
    write_csv(HERE/"kalshi_playoff_model_comparison.csv",kalshi_rows)
    write_csv(HERE/"kalshi_playoff_metrics.csv",kalshi_metrics)
    selected={"moneyline_by_validation_brier":best_win,"goal_distribution_by_validation_joint_nll":best_goal,
              "kalshi_comparison_model":best_win}
    summary={"protocol":"backtest_preregistration_v1.md","preregistration_sha256":prereg_sha,
        "canonical_sha256":sha(CANONICAL),"features_sha256":sha(FEATURES),"market_prices_used_in_statistical_features":False,
        "split":{"fit_seasons":"2008-2017","validation_seasons":"2018-2021","locked_test_seasons":"2022-2024","untouched_final_season":"2025-2026"},
        "selection":{"elo_grid":elo_grid,"elo_selected":{"k":elo_k,"home_ice_elo":elo_hfa},
            "recent_form_grid":recent_grid,"recent_form_selected_c":recent_best["C"],
            "poisson_alpha_grids":alpha_grids,"poisson_selected_alpha":alphas,"locked_leaders":selected},
        "fit_only":{"train_games":sum(r["season"]<=TRAIN_END for r in games),"train_games_after_refit_through_2021":sum(r["season"]<=2021 for r in games)},
        "validation_metrics":val_metrics,"test_metrics_by_season":[x for x in metrics if x["season"]>=2022],
        "paired_differences":paired,"kalshi_games":len(kalshi_rows),"kalshi_comparison_model":best_win,
        "kalshi_model_metrics":chosen,"kalshi_market_metrics":market,"kalshi_paired_brier_delta_model_minus_market":kalshi_delta,
        "artifact_sha256":{}}
    for fname in ["baseline_predictions_validation.csv","baseline_predictions_holdout_2022_2025.csv","baseline_metrics_by_season.csv",
                  "baseline_paired_differences.csv","kalshi_playoff_model_comparison.csv","kalshi_playoff_metrics.csv"]:
        summary["artifact_sha256"][fname]=sha(HERE/fname)
    (HERE/"baseline_ladder_results.json").write_text(json.dumps(summary,indent=2)+"\n")
    report=make_report(summary,metrics,paired,kalshi_metrics,chosen,market,kalshi_delta)
    (HERE/"nhl_baseline_ladder_results.md").write_text(report)
    print(json.dumps({"selected":selected,"validation_games":len(valpred),"holdout_games":len(holdpred),
        "kalshi_games":len(kalshi_rows),"kalshi_model":chosen,"kalshi_market":market,
        "paired_brier_model_minus_market":kalshi_delta},indent=2))


def make_report(summary,metrics,paired,kalshi_metrics,chosen,market,delta):
    lines=["# NHL statistical baseline ladder: evaluation results","",
        f"Protocol preregistration SHA-256: `{summary['preregistration_sha256']}`. See `backtest_preregistration_v1.md` for fixed splits and selection rules.",
        "No market price was used as a model feature. Statistical goals use NHL regulation/overtime goals with the shootout decider removed; moneyline labels use official NHL winners including shootouts.",
        "","## Model selection and lock","",
        f"Validation selected Elo K={summary['selection']['elo_selected']['k']} and home-ice offset={summary['selection']['elo_selected']['home_ice_elo']}; recent-form logistic C={summary['selection']['recent_form_selected_c']}; Poisson alphas: `{json.dumps(summary['selection']['poisson_selected_alpha'],sort_keys=True)}`.",
        f"Validation leaders: moneyline **{summary['selection']['locked_leaders']['moneyline_by_validation_brier']}** by Brier; goal distribution **{summary['selection']['locked_leaders']['goal_distribution_by_validation_joint_nll']}** by joint score NLL. Coefficients were then refit only through 2021; all 2022–26 results are held out.",
        "","## Score prediction: does xG improve over Elo and historical goals?","",
        "Lower is better. Test comparisons use the exact same games; paired intervals resample games. `B3` is the Elo-to-goals mapping, `B4` uses rolling historical goals, `B5` uses rolling 5-on-5 score/venue-adjusted xG, and `B6` combines goals and xG.",
        "","| Sample | Model | Games | Goals MAE / team | Total goals MAE | Joint goal NLL |",
        "| --- | --- | ---: | ---: | ---: | ---: |"]
    for sample_name, sample_seasons in (("2022–24 aggregate", set(range(2022,2025))), ("2025–26 final season", {2025})):
        for model in ("B3","B4","B5","B6"):
            subset=[x for x in metrics if x["target"]=="goals" and x["model"]==model and x["season"] in sample_seasons]
            n=sum(x["n"] for x in subset)
            if n:
                avg=lambda field:sum(x[field]*x["n"] for x in subset)/n
                lines.append(f"| {sample_name} | {model} | {n} | {avg('goals_mae_per_team'):.4f} | {avg('total_goals_mae'):.4f} | {avg('joint_poisson_nll'):.4f} |")
    for x in metrics:
        if x["target"]=="goals" and x["model"] in ("B3","B4","B5","B6") and (x["season"]>=2022):
            lines.append(f"| {x['season']} ({x['split']}) | {x['model']} | {x['n']} | {x['goals_mae_per_team']:.4f} | {x['total_goals_mae']:.4f} | {x['joint_poisson_nll']:.4f} |")
    lines += ["","### Paired xG deltas","","Positive loss delta means xG model is worse than comparator; negative means it is better. 95% intervals are game-bootstrap intervals.","",
        "| Sample | xG model minus | Metric | Delta | 95% interval | Games |","| --- | --- | --- | ---: | ---: | ---: |"]
    for x in paired:
        if x["model_a"] in ("B5","B6") and x["metric"] in ("per_game_team_goals_mae","joint_goal_nll"):
            lines.append(f"| {x['sample']} | {x['model_b']} | {x['metric']} | {x['delta_a_minus_b']:.5f} | [{x['ci95_low']:.5f}, {x['ci95_high']:.5f}] | {x['n_games']} |")
    lines += ["","## Moneyline probability and calibration by season","","Brier ranges from 0 (perfect) to 1 (worst); 0.25 is the score for constant 50% predictions. Because the NHL home-win rate is not exactly 50%, compare against B1's training-set home-win rate as well. Brier, log loss and ECE are lower-is-better. Calibration slope near 1 and intercept near 0 are ideal. Season metrics and all baselines are in `baseline_metrics_by_season.csv`.","",
        "| Season | Model | Games | Brier | Log loss | Cal. intercept | Cal. slope | ECE |","| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for x in metrics:
        if x["target"]=="moneyline":
            lines.append(f"| {x['season']} | {x['model']} | {x['n']} | {x['brier']:.4f} | {x['log_loss']:.4f} | {x['calibration_intercept']:.3f} | {x['calibration_slope']:.3f} | {x['ece_10_bins']:.4f} |")
    lines += ["","## Separate Kalshi playoff comparison","",
        f"Frozen comparison model: **{summary['kalshi_comparison_model']}** (chosen on validation Brier). Matched games: **{summary['kalshi_games']}**. Kalshi probability is the home contract YES midpoint normalized against the away contract YES midpoint; both quotes are from the audited pregame snapshot. No quote was used for fitting or selection.",
        "","| Forecast | Games | Brier | Log loss | Cal. intercept | Cal. slope | ECE |","| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    for x in kalshi_metrics:
        lines.append(f"| {x['model']} | {x['n']} | {x['brier']:.4f} | {x['log_loss']:.4f} | {x['calibration_intercept']:.3f} | {x['calibration_slope']:.3f} | {x['ece_10_bins']:.4f} |")
    lines += ["",f"Paired Brier loss difference (frozen model minus Kalshi): {delta['delta_a_minus_b']:.5f}, 95% game-bootstrap interval [{delta['ci95_low']:.5f}, {delta['ci95_high']:.5f}]. This 80-game sample is imprecise; it is an evaluation, not proof of a trading edge.",
        "","## Limitations and reproducibility","",
        "The final season and its Kalshi comparison were excluded from model selection. The statistical test covers the exact feature-ready rows, with model-specific paired metrics. The model uses no goalie or lineup inputs. Kalshi market comparison uses midpoints and evaluates probability accuracy, not executable returns, fees, liquidity, or trading performance.",
        "Prediction rows are in `baseline_predictions_validation.csv` and `baseline_predictions_holdout_2022_2025.csv`; all score and probability metrics are in `baseline_metrics_by_season.csv`; paired deltas are in `baseline_paired_differences.csv`; the separate market sample is in `kalshi_playoff_model_comparison.csv`."]
    return "\n".join(lines)+"\n"


if __name__=="__main__":main()
