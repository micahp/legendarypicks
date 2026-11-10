import concurrent.futures, gzip, hashlib, json, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

REPO=Path("/root/ot-sim-out/slc-v2-profile-checkout")
OUT=Path("/root/ot-sim-out/slc-v2-three-way-2026-11-10")
DB=Path("/root/legendarypicks/backend/data/picks.dev.db")
SNAP_COUNTS=Path("/root/ot-sim-out/slc-v2-profile-inputs-2026-11-09/snap-counts-through-week-8.json")
D1_INPUT=REPO/"docs/research/slc-workload-calibration-2026-11-08/frozen-evaluation/inputs.json.gz"
ARTIFACT=REPO/"docs/research/SLC-PLAYCALL-ARTIFACT-v1.json"
STREAKS=Path("/tmp/bench/wl-streaks-2026-11-07.json")
SNAP_SHA="36f28e18af3080df9f160d42dd5e3e59c37cfacf0dd24772ea51cfd41cadcfca"
D1_SHA="cec16cb2462ef71eaf0fc5d300ce6729e57c915b114dd8615f8e7d924986a618"
BLOCKERS=["run_scramble_backoff","long_field_goal_feasibility","blocked_kick_source_audit","blocked_kick_geometry","safety_free_kick_boundaries"]
MATCHUPS=[("ARI_SEA",334,300001), ("DAL_IND",333,300335), ("DEN_CAR",333,300668)]


def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def write(obj):
    p=OUT/"manifest.json"
    tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")
    tmp.replace(p)
def gzip_verified(src):
    digest=sha(src); target=src.with_name(src.name+".gz")
    with src.open("rb") as fi, target.open("wb") as fo:
        with gzip.GzipFile(filename="",mode="wb",compresslevel=1,fileobj=fo,mtime=0) as gz:
            shutil.copyfileobj(fi,gz,1024*1024)
    restored=hashlib.sha256()
    with gzip.open(target,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): restored.update(b)
    if restored.hexdigest()!=digest: raise RuntimeError("gzip verification failed: "+str(src))
    return {"sha256":digest,"bytes":src.stat().st_size,"gzip":target.name,
            "gzip_sha256":sha(target),"gzip_bytes":target.stat().st_size}
def command(arm, matchup, count, start, control=None):
    snapshot=OUT/"snapshots"/("2026_09_"+matchup+".json")
    stem=f"{arm.lower()}-{matchup}-{start}-{start+count-1}"
    out=OUT/"workers"/(stem+".json")
    cmd=[sys.executable,str(REPO/"scripts/nfl_sequence/simulate_pregame_batch.py"),
         "--snapshot-file",str(snapshot),"--db",str(DB),"--slc-profile","v1_full_stack","--slc-v2",
         "--rng-protocol","v2","--playcall-artifact",str(ARTIFACT),"--playcall-streak-file",str(STREAKS),
         "--slc-fg-ordinary-cutoff","60.0","--participation-snap-counts",str(SNAP_COUNTS),
         "--participation-snap-counts-sha256",SNAP_SHA,"--games",str(count),"--seed-start",str(start),
         "--progress-every","100","--export-boxscores","--max-simulation-errors","1000","--out",str(out)]
    if arm=="C": cmd += ["--experimental-workload-estimator","C"]
    elif arm=="D1": cmd += ["--experimental-workload-estimator","D1","--workload-adaptive-input",str(D1_INPUT),
                              "--workload-adaptive-sha256",D1_SHA]
    if control: cmd += ["--paired-workload-baseline-ledger",str(control)]
    for blocker in BLOCKERS: cmd += ["--slc-blocker-fix",blocker]
    return stem,out,cmd

def execute(job, keep_control_ledger=False):
    arm,matchup,count,start,control=job
    stem,out,cmd=command(arm,matchup,count,start,control)
    log=OUT/"workers"/(stem+".log")
    with log.open("w") as f: result=subprocess.run(cmd,cwd=REPO,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode: raise RuntimeError(f"{stem} exited {result.returncode}; see {log}")
    files=[out,OUT/"workers"/(stem+".seeds.jsonl"),OUT/"workers"/(stem+".boxscores.jsonl")]
    artifacts={}
    for src in files:
        if not src.is_file(): raise RuntimeError(f"{stem} missing output {src.name}")
        artifacts[src.name]=gzip_verified(src)
        if not (keep_control_ledger and src.name.endswith(".seeds.jsonl")): src.unlink()
    return {"arm":arm,"matchup":matchup,"seed_start":start,"seed_end":start+count-1,
            "games":count,"artifacts":artifacts,"control_ledger":str(files[1]) if keep_control_ledger else None,
            "log":str(log)}

def main():
    for p in (DB,SNAP_COUNTS,D1_INPUT,ARTIFACT,STREAKS):
        if not p.is_file(): raise FileNotFoundError(p)
    if sha(SNAP_COUNTS)!=SNAP_SHA or sha(D1_INPUT)!=D1_SHA: raise ValueError("frozen input hash mismatch")
    snaps={}
    for matchup,count,start in MATCHUPS:
        p=OUT/"snapshots"/("2026_09_"+matchup+".json")
        if not p.is_file(): raise FileNotFoundError(p)
        doc=json.loads(p.read_text())
        snaps[matchup]={"path":str(p),"sha256":sha(p),"as_of":doc["as_of"],"game_id":doc["schedule"]["game_id"]}
    source_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=REPO,text=True).strip()
    manifest={"status":"running","started_at_utc":now(),"source_commit":source_commit,
      "source_status":subprocess.check_output(["git","status","--short"],cwd=REPO,text=True).strip(),
      "requested_per_arm":1000,"workers":2,"matchups":snaps,"seed_ranges":{},
      "arms":{"default_v2":[],"C":[],"D1":[]},"failures":[],
      "snapshot_validity":"preserved from each frozen input; pre-final roster timing does not invalidate a game snapshot",
      "participation_snap_counts_sha256":SNAP_SHA,"adaptive_workload_input_sha256":D1_SHA,
      "database_sha256":sha(DB),"playcall_artifact_sha256":sha(ARTIFACT),
      "streak_file_sha256":sha(STREAKS),"blocker_fixes":BLOCKERS,
      "pairing":"Default V2 is the control ledger. C and D1 are separately paired to its per-matchup RNG-v2 root."}
    write(manifest)
    controls=[]
    for matchup,count,start in MATCHUPS:
        manifest["seed_ranges"][matchup]={"count":count,"start":start,"end":start+count-1}
        controls.append(("default_v2",matchup,count,start,None))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(execute,j,True):j for j in controls}
        for future in concurrent.futures.as_completed(futures):
            result=future.result(); manifest["arms"]["default_v2"].append(result); write(manifest)
    treatment_jobs=[]
    for arm in ("C","D1"):
        for matchup,count,start in MATCHUPS:
            ledger=OUT/"workers"/(f"default_v2-{matchup}-{start}-{start+count-1}.seeds.jsonl")
            treatment_jobs.append((arm,matchup,count,start,ledger))
    def worker_arm(arm):
        results=[]
        for job in [j for j in treatment_jobs if j[0]==arm]:
            results.append(execute(job))
            manifest["arms"][arm].extend(results[-1:]); write(manifest)
        return results
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker_arm,arm) for arm in ("C","D1")]
        for future in concurrent.futures.as_completed(futures): future.result()
    for item in manifest["arms"]["default_v2"]:
        Path(item["control_ledger"]).unlink()
    manifest.update({"status":"complete","completed_at_utc":now(),
      "completed_per_arm":{arm:sum(x["games"] for x in rows) for arm,rows in manifest["arms"].items()}})
    write(manifest)

if __name__=="__main__":
    try: main()
    except Exception as e:
        (OUT/"failure.json").write_text(json.dumps({"failed_at_utc":now(),"error":repr(e)},indent=2)+"\n")
        raise
