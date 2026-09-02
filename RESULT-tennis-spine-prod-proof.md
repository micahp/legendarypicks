# Tennis spine production-copy proof

## Answer

On the production copy, the candidate tennis spine published **150 of 150 ATP**
and **150 of 150 WTA** ESPN identities. The candidate resolver then resolved
**101 of 115 ATP** rejected names and **112 of 132 WTA** rejected names:
**213 of 247** total (86.2%). That clears the candidate scraper's per-league
zero-resolution exit-3 condition.

**This is not a data-only way to turn the current production service green.**
The running five-day-old production container lacks the candidate resolver's
`2b. Folded name on both sides` branch. Its resolver is therefore not the
resolver that produced the 213-of-247 result below. Do not apply the spine to
production until that container code is rebuilt/deployed as well.

No production DB write, service action, code edit, or Git action was performed.

## Production DB integrity

START:

```text
9ee2760e1a10e012319e4ad48edd84a9  /root/legendarypicks/backend/data/picks.db
```

END:

```text
9ee2760e1a10e012319e4ad48edd84a9  /root/legendarypicks/backend/data/picks.db
```

The identical start/end hashes are from `md5sum` of the production DB. All
database writes below were directed to
`/tmp/tennis-prod-proof/prod-copy.db`.

## Step 1 — copied-production baseline

Command used to make the disposable copy:

```sh
mkdir -p /tmp/tennis-prod-proof
cp /root/legendarypicks/backend/data/picks.db /tmp/tennis-prod-proof/prod-copy.db
```

Baseline output from that copy (the `props` count is joined through
`prop_games`, which owns the league column):

```text
atp: players 0; prop_games 134; props 0; unresolved_players 115
wta: players 0; prop_games 163; props 0; unresolved_players 132
atp+wta unresolved_players 247
```

## Step 2 — spine run on the copy

Before the run, the declared ESPN spend was **2 of 2 requests** to
`site.web.api.espn.com`: one bulk rankings request for ATP and one for WTA.
No per-athlete request was made.

```sh
cd /root/lp-tennis-spine/backend
LP_DB_PATH=/tmp/tennis-prod-proof/prod-copy.db \
  /root/legendarypicks/backend/venv/bin/python ingest_tennis_players.py
```

Real output:

```text
database: /tmp/tennis-prod-proof/prod-copy.db
request plan: site.web.api.espn.com 2 of 2 (one bulk rankings request per league; no per-athlete requests)
atp: published 150 of 150 ESPN ranking athletes
  unique ESPN ids 150 of 150; active 148 of 150; sha256 a23bd33a09d3
  matched 0 of 150 existing ESPN ids; inserted 150 of 150; refreshed 0 of 150; unchanged 0 of 150
wta: published 150 of 150 ESPN ranking athletes
  unique ESPN ids 150 of 150; active 129 of 150; sha256 5bd583bba39c
  matched 0 of 150 existing ESPN ids; inserted 150 of 150; refreshed 0 of 150; unchanged 0 of 150
requests spent: site.web.api.espn.com 2 of 2
```

After-run output from the same copy:

```text
atp: players 150; prop_games 134; props 0; unresolved_players 115
wta: players 150; prop_games 163; props 0; unresolved_players 132
atp+wta unresolved_players 247
```

The spine added **150 of 150** player identities per league (**300 of 300**)
and did not create props. The original rejection rows remain as the exact
resolver-test input.

## Step 3 — exact rejected-name resolution on the copy

I passed the exact `unresolved_players` ATP/WTA names and teams through the
candidate branch's real `_core._resolve_player_for_ingest` against the copied
DB. The resolver calls were inside a transaction that was rolled back, so this
test did not alter the copied rejection rows.

```text
input unresolved names: 247 of 247
atp: resolved 101 of 115; failed 14 of 115
wta: resolved 112 of 132; failed 20 of 132
atp+wta: resolved 213 of 247; failed 34 of 247
```

Rates and shortfalls: ATP **101 of 115** (87.8%; 14 fail), WTA **112 of 132**
(84.8%; 20 fail), combined **213 of 247** (86.2%; 34 fail).

Every remaining name was absent from the copied 150-player ESPN ranking spine
after the resolver's deterministic folding; no identity was invented.

| League | Still unresolved player | Opponent/team recorded with the rejection | Reason |
| --- | --- | --- | --- |
| atp | Stefanos Sakellaridis | MARTIN DAMM JR | Absent from copied ESPN ranking spine |
| atp | J.J. Wolf | SHINTARO MOCHIZUKI | Absent from copied ESPN ranking spine |
| atp | Darwin Blanch | ALEKSANDAR VUKIC | Absent from copied ESPN ranking spine |
| atp | Mark Lajal | DALIBOR SVRCINA | Absent from copied ESPN ranking spine |
| atp | Alexander Shevchenko | CHRISTOPHER O'CONNELL | Absent from copied ESPN ranking spine |
| atp | Daniel Merida Aguilar | MARIN CILIC | Absent from copied ESPN ranking spine |
| atp | Juncheng Shang | LORENZO SONEGO | Absent from copied ESPN ranking spine |
| atp | Thanasi Kokkinakis | NUNO BORGES | Absent from copied ESPN ranking spine |
| atp | Gael Monfils | RINKY HIJIKATA | Absent from copied ESPN ranking spine |
| atp | Pablo Carreno-Busta | TOMAS MACHAC | Absent from copied ESPN ranking spine |
| atp | Yibing Wu | JAIME FARIA | Absent from copied ESPN ranking spine |
| atp | Kei Nishikori | MARCO TRUNGELLITI | Absent from copied ESPN ranking spine |
| atp | Trevor Svajda | MICHAEL ZHENG | Absent from copied ESPN ranking spine |
| atp | Nicolai Budkov Kjaer | KYRIAN JACQUET | Absent from copied ESPN ranking spine |
| wta | Lin Zhu | LILLI TAGGER | Absent from copied ESPN ranking spine |
| wta | Yue Yuan | RENATA ZARAZUA | Absent from copied ESPN ranking spine |
| wta | Robin Montgomery | JULIA GRABHER | Absent from copied ESPN ranking spine |
| wta | Elizabeth Mandlik | OKSANA SELEKHMETEVA | Absent from copied ESPN ranking spine |
| wta | Polina Iatcenko | CLAIRE LIU | Absent from copied ESPN ranking spine |
| wta | Varvara Lepchenko | ALINA KORNEEVA | Absent from copied ESPN ranking spine |
| wta | Akasha Urhobo | HANNE VANDEWINKEL | Absent from copied ESPN ranking spine |
| wta | Rebecca Marino | ALINA CHARAEVA | Absent from copied ESPN ranking spine |
| wta | Aoi Ito | SOLANA SIERRA | Absent from copied ESPN ranking spine |
| wta | Nadia Podoroska | ELLA SEIDEL | Absent from copied ESPN ranking spine |
| wta | Xiyu Wang | BIANCA ANDREESCU | Absent from copied ESPN ranking spine |
| wta | Bianca Andreescu | XIYU WANG | Absent from copied ESPN ranking spine |
| wta | Lois Boisson | ASHLYN KRUEGER | Absent from copied ESPN ranking spine |
| wta | Yulia Starodubtseva | DARIA SNIGUR | Absent from copied ESPN ranking spine |
| wta | Caroline Dolehide | DIANE PARRY | Absent from copied ESPN ranking spine |
| wta | Maria Camila Osorio | TAYLOR TOWNSEND | Absent from copied ESPN ranking spine |
| wta | Venus Williams | EMILIANA ARANGO | Absent from copied ESPN ranking spine |
| wta | Xinyu Wang | HANNE VANDEWINKEL | Absent from copied ESPN ranking spine |
| wta | Sloane Stephens | SINJA KRAUS | Absent from copied ESPN ranking spine |
| wta | Shuai Zhang | KAYLA DAY | Absent from copied ESPN ranking spine |

## Step 4 — candidate exit rule

**Yes, for the candidate branch's zero-resolution exit rule:** ATP resolves
101 of 115 and WTA resolves 112 of 132, so neither league has zero resolved.
The relevant code in `backend/bovada_scraper.py` is:

```python
resolved = c["ingested"] + c["refreshed"]
if c["scraped"] and not resolved:
    print(f"      REJECTED all {c['scraped']} {lg} props —"
          f" nothing in `players` matched. A count of zero is a finding.")
    problems.append(f"{lg} resolved 0 of {c['scraped']}")

if problems:
    print("\nEXIT 3 — " + "; ".join(problems))
    return 3
print("  no problems found")
return 0
```

This copy proof did not run a scraper or service, so it does not measure an
unrelated `games_failed` problem. It proves the specific ATP/WTA
zero-resolution condition is cleared by the candidate resolver, not that the
current container will produce that result.

## Step 5 — cost and current-container compatibility

The command that would apply the identity spine to production is deliberately
**not run**:

```sh
cd /root/lp-tennis-spine/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
  /root/legendarypicks/backend/venv/bin/python ingest_tennis_players.py
```

Against the measured empty production tennis population, it would atomically
insert **150 of 150 ATP** and **150 of 150 WTA** `players` rows, each with the
publisher name, `team=NULL`, league, ESPN ID, active flag, and timestamp. It
does not write props. It is identity-idempotent: publication is planned by
existing ESPN ID, inserts occur only for missing IDs, and unchanged source
identities are not duplicated; changed source fields update the existing row.

**Most important: do not apply this as a data-only fix.** Read-only inspection
of running container `a8057e1d2701` found its `/app/data` mounted from
`/root/legendarypicks/backend/data`, so new DB rows would be visible to it, but
the container has no `/app/ingest_tennis_players.py` and its `/app/_core.py`
resolver has steps 1, 2, and 3 only. The candidate `_core.py` used for the
213-of-247 proof additionally has `2b. Folded name on both sides
(diacritics/case/punctuation)` and its `_folded_name_index` lookup; that block
is absent from the production container. The container therefore needs code it
does not have, and the current production service must not be claimed green
from the spine rows alone.

Stopped here. Nothing was applied to production.
