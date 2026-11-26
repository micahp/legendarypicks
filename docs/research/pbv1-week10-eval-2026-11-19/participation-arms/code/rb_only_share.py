import collections, gzip, json, re, sqlite3, statistics
CAMP="/root/tnf-batch/camp"; DB="/root/tnf-batch/picks.frozen.db"
NORM={"WSH":"WAS","LAR":"LA"}
n=lambda t: NORM.get(t,t)
con=sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
pos={k:p for k,p in con.execute("select nfl_gsis_id, position from players where nfl_gsis_id is not null")}
logs=collections.defaultdict(dict)
for g,k,t,s in con.execute("select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league=\x27nfl\x27 and game_id like \x272026_10_%\x27 and game_type=\x27REG\x27"):
    d=json.loads(s) if s else {}; logs[g][k]=(n(t), d.get("carries") or 0)
con.close()
def firsts(folder,g):
    data=json.load(gzip.open("%s/%s/%s/choices.json.gz" % (CAMP,folder,g),"rt"))
    calls=collections.defaultdict(list)
    for d in data["draws"]:
        m=re.search(r":(\d+):(\d+):field:advance$", d["draw"])
        if m: calls[(int(m.group(1)),int(m.group(2)))].append(d)
    by=collections.defaultdict(list)
    for p in data["plays"]: by[(n(p["team"]),p["seed"])].append(p)
    return {k: min(v,key=lambda p:p["index"]) for k,v in by.items()}, calls
res={"HS":[], "HE":[]}; allc={"HS":[], "HE":[]}; other_pos=collections.Counter()
for g in sorted(logs):
    fs,cs=firsts("HS",g); fe,ce=firsts("HE",g)
    for key,p in fs.items():
        q=fe.get(key)
        if q is None or q["index"]!=p["index"]: continue
        if (p["lineup"] or {}).get("group")!="11" or (q["lineup"] or {}).get("group")!="11": continue
        team,seed=key
        rbs=[(c,k) for k,(t,c) in logs[g].items() if t==team and pos.get(k)=="RB"]
        if not rbs: continue
        lead=max(rbs)[1]
        def call(pl,calls):
            h=[k for k,v in ((pl["lineup"] or {}).get("slots") or {}).items() if v=="RB"]
            if not h: return None
            for c in calls.get((seed,pl["index"]),[]):
                if h[0] in c["chosen"] and lead in c["ids"]: return c
            return None
        a=call(p,cs); b=call(q,ce)
        if a is None or b is None or a["ids"]!=b["ids"]: continue
        for name,c in (("HS",a),("HE",b)):
            w=dict(zip(c["ids"],c["weights"]))
            rb_ids=[i for i in c["ids"] if pos.get(i)=="RB"]
            tot_rb=sum(w[i] for i in rb_ids)
            if lead in w and tot_rb>0: res[name].append(w[lead]/tot_rb)
            for i in c["ids"]:
                if pos.get(i)!="RB": other_pos[(name, pos.get(i))]+=1
for name in ("HS","HE"):
    print(name, "lead share among RB candidates: mean %.3f, n %d" % (statistics.mean(res[name]), len(res[name])))
print("non-RB candidates in group-11 RB draws (HS, HE):", {k[1]:v for k,v in other_pos.items() if k[0]=="HS"}, {k[1]:v for k,v in other_pos.items() if k[0]=="HE"})
