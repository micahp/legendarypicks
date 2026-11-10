import concurrent.futures, gzip, hashlib, json, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

REPO=Path("/root/ot-sim-out/slc-v2-profile-checkout")
DB=Path("/root/legendarypicks/backend/data/picks.dev.db")
OUT=Path("/root/ot-sim-out/slc-v2-model-d1-10k-2026-11-10")
SNAPSHOT=Path("/root/ot-sim-out/buf-min-10k-2026-11-09/snapshot.json")
SNAP_COUNTS=Path("/root/ot-sim-out/slc-v2-profile-inputs-2026-11-09/snap-counts-through-week-8.json")
D1_INPUT=REPO/"docs/research/slc-workload-calibration-2026-11-08/frozen-evaluation/inputs.json.gz"
ARTIFACT=REPO/"docs/research/SLC-PLAYCALL-ARTIFACT-v1.json"
STREAKS=Path("/tmp/bench/wl-streaks-2026-11-07.json")
WORKERS=OUT/"workers"
MANIFEST=OUT/"manifest.json"
CHUNK=250
CONCURRENCY=4
SEED_START=200001
TOTAL=10000
D1_SHA="cec16cb2462ef71eaf0fc5d300ce6729e57c915b114dd8615f8e7d924986a618"
SNAP_SHA="36f28e18af3080df9f160d42dd5e3e59c37cfacf0dd24772ea51cfd41cadcfca"
BLOCKERS=["run_scramble_backoff","long_field_goal_feasibility","blocked_kick_source_audit","blocked_kick_geometry","safety_free_kick_boundaries"]

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def write(obj): MANIFEST.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")
def archive(job):
    stem,start,count=job
    out=WORKERS/(stem+".json")
    cmd=[sys.executable,str(REPO/"scripts/nfl_sequence/simulate_pregame_batch.py"),
         "--snapshot-file",str(SNAPSHOT),"--db",str(DB),"--slc-profile","v1_full_stack","--slc-v2",
         "--rng-protocol","v2","--playcall-artifact",str(ARTIFACT),"--playcall-streak-file",str(STREAKS),
         "--slc-fg-ordinary-cutoff","60.0","--participation-snap-counts",str(SNAP_COUNTS),
         "--participation-snap-counts-sha256",SNAP_SHA,
         "--experimental-workload-estimator","D1","--workload-adaptive-input",str(D1_INPUT),
         "--workload-adaptive-sha256",D1_SHA,
         "--games",str(count),"--seed-start",str(start),"--resume","--progress-every","100",
         "--export-boxscores","--max-simulation-errors","1000","--out",str(out)]
    for blocker in BLOCKERS: cmd += ["--slc-blocker-fix",blocker]
    log=WORKERS/(stem+".log")
    with log.open("w") as f: result=subprocess.run(cmd,cwd=REPO,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode: raise RuntimeError(f"{stem} exited {result.returncode}; see {log}")
    paths=[out,WORKERS/(stem+".seeds.jsonl"),WORKERS/(stem+".boxscores.jsonl")]
    artifacts={}
    for src in paths:
        if not src.is_file(): raise RuntimeError(f"{stem} missing output {src.name}")
        digest=sha(src); target=src.with_name(src.name+".gz")
        with src.open("rb") as fi,target.open("wb") as fo:
            with gzip.GzipFile(filename="",mode="wb",compresslevel=1,fileobj=fo,mtime=0) as gz:
                shutil.copyfileobj(fi,gz,1024*1024)
        with gzip.open(target,"rb") as f:
            restored=hashlib.sha256()
            for b in iter(lambda:f.read(1024*1024),b""): restored.update(b)
        if restored.hexdigest()!=digest: raise RuntimeError(f"gzip verification failed for {src.name}")
        artifacts[src.name]={"sha256":digest,"bytes":src.stat().st_size,"gzip":target.name,
                             "gzip_sha256":sha(target),"gzip_bytes":target.stat().st_size}
        src.unlink()
    return {"worker":stem,"seed_start":start,"seed_end":start+count-1,"games":count,
            "artifacts":artifacts,"log":str(log)}

def main():
    for p in (DB,SNAPSHOT,SNAP_COUNTS,D1_INPUT,ARTIFACT,STREAKS):
        if not p.is_file(): raise FileNotFoundError(p)
    if sha(SNAP_COUNTS)!=SNAP_SHA or sha(D1_INPUT)!=D1_SHA:
        raise ValueError("frozen workload or snap-count input hash mismatch")
    WORKERS.mkdir(parents=True,exist_ok=True)
    snap=json.loads(SNAPSHOT.read_text())
    manifest={"status":"running","started_at_utc":now(),"game_id":snap["schedule"]["game_id"],
      "requested_games":TOTAL,"seed_start":SEED_START,"seed_end":SEED_START+TOTAL-1,
      "snapshot_sha256":sha(SNAPSHOT),"snapshot_as_of":snap["as_of"],
      "snapshot_validity":"valid_before_roster_finalization",
      "roster_finalization_timing":snap.get("roster_finalization_timing",{"status":"before_roster_finalization"}),
      "source_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=REPO,text=True).strip(),
      "source_status":subprocess.check_output(["git","status","--short"],cwd=REPO,text=True).strip(),
      "database_sha256":sha(DB),"playcall_artifact_sha256":sha(ARTIFACT),"streak_file_sha256":sha(STREAKS),
      "participation_snap_counts_sha256":SNAP_SHA,"adaptive_workload_input_sha256":D1_SHA,
      "slc_profile":"v1_full_stack+slc-v2","workload_estimator":"D1",
      "rng_protocol":"v2","blocker_fixes":BLOCKERS,
      "input_provenance_note":"Snap-count file acquisition followed the game snapshot; this is separate from valid pre-final-roster snapshot status.",
      "workers_directory":str(WORKERS),"workers":[],"failures":[]}
    write(manifest)
    jobs=[]
    for start in range(SEED_START,SEED_START+TOTAL,CHUNK):
        count=min(CHUNK,SEED_START+TOTAL-start)
        jobs.append((f"seed-{start:06d}-{start+count-1:06d}",start,count))
    for offset in range(0,len(jobs),CONCURRENCY):
        batch=jobs[offset:offset+CONCURRENCY]
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures=[pool.submit(archive,job) for job in batch]
            for future in concurrent.futures.as_completed(futures):
                manifest["workers"].append(future.result()); write(manifest)
    manifest.update({"status":"complete","completed_at_utc":now(),"completed_games":sum(x["games"] for x in manifest["workers"])})
    write(manifest)

if __name__=="__main__":
    try: main()
    except Exception as e:
        (OUT/"failure.json").write_text(json.dumps({"failed_at_utc":now(),"error":repr(e)},indent=2)+"\n")
        raise
