"""Strict availability check for Out or Doubtful carriers with no log row (arms B and C).

A designation counts as verified before the forecast cutoff only if a team injury article:
  - was published in the 7 days up to and including the game's snapshot cutoff date,
  - names the player in full, and
  - uses an out-status word in its title.
Anything else is reported as not verified. Nothing is labeled an avoidable error without that check.
"""
import datetime, json, re, sqlite3

DB = '/root/tnf-batch/picks.frozen.db'
SRC = '/root/tnf-batch/audit/analysis/investigation_v2.json'
OUT = '/root/tnf-batch/audit/analysis/availability_strict.json'
OUT_RE = re.compile(r'\b(out|ruled out|inactive|injured reserve|doubtful|will not play|on ir)\b', re.I)

rows = json.load(open(SRC))['availability_rows']
con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
articles = con.execute("select published_date, team, title from team_injury_articles where published_date >= '2026-10-25'").fetchall()
con.close()

result = {}
for arm, items in rows.items():
    tally = {'verified_pre_cutoff': 0, 'not_verified': 0}
    carries = {'verified_pre_cutoff': 0.0, 'not_verified': 0.0}
    detail = []
    for x in items:
        cut = datetime.date.fromisoformat(x['cutoff'][:10])
        start = cut - datetime.timedelta(days=7)
        hits = []
        for d, t, title in articles:
            if not (start.isoformat() <= d <= cut.isoformat()):
                continue
            if x['name'] in title and OUT_RE.search(title) and 'out of practice' not in title.lower():
                hits.append((d, title))
        cat = 'verified_pre_cutoff' if hits else 'not_verified'
        tally[cat] += 1
        carries[cat] += x['carries']
        detail.append({'game': x['game'], 'name': x['name'], 'status': x['status'], 'carries': x['carries'],
                       'cutoff': x['cutoff'], 'category': cat, 'matches': hits[:3]})
    result[arm] = {'players': tally, 'carries': {k: round(v, 2) for k, v in carries.items()}, 'detail': detail}

with open(OUT, 'w') as f:
    json.dump(result, f, indent=1)
for arm in result:
    print(arm, result[arm]['players'], result[arm]['carries'])
    for x in result[arm]['detail']:
        if x['category'] == 'verified_pre_cutoff':
            print('   ', x['game'][5:], x['name'], x['status'], x['carries'], x['matches'][0])
