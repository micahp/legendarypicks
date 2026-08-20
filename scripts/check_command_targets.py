#!/usr/bin/env python3
"""Every command host config names, checked for existence. Exit 1 if any is dead.

## Why

On 2026-08-18 ten modules were split into packages. The Python side came out
clean: 0 undefined names under pyflakes, suite green. Everything that broke
broke OUTSIDE python, because a split cannot see a caller that is not an import:

  /etc/cron.d/legendarypicks-pipeline   still ran `bovada_scraper.py`, dead for
                                        7 consecutive runs. The REPO copy of the
                                        same cron was fixed; the installed copy
                                        was never reinstalled.
  scripts/release.sh                    guarded the prod stats audit behind
                                        `[ -f backend/audit_league_stats.py ]`,
                                        so it skipped silently for two releases.
  verify-gates.sh                       read python's "can't open file" exit 2
                                        as 2 failures against a known 21.

The dispatch specs are why. They said "keep the full external surface working,
verify with an import smoke test, the test files, and the importers check" --
every verification inside the language. The agents satisfied that correctly.
"External" stopped at the python boundary, and cron did not.

So this asks the question those checks cannot: does the thing this line RUNS
exist? It reads installed host config, not the repo copy, because the gap
between them is itself a defect this found.
"""

import os, re, glob

TOKEN = re.compile(r"[A-Za-z0-9_./$-]+\.py\b")
VAR = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)=(\S+)", re.M)

targets = sorted(glob.glob("/etc/cron.d/legendarypicks*")) + \
          sorted(glob.glob("/etc/systemd/system/legendarypicks-*.service"))
try:
    import subprocess
    ct = subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL).decode()
except Exception:
    ct = ""

def _live(text):
    """Only lines that actually run. A commented-out cron line names a command
    that no longer executes, and flagging it trains people to ignore this."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        out.append(line)
    return "\n".join(out)


def check(name, text):
    text = _live(text)
    env = dict(VAR.findall(text))
    # systemd WorkingDirectory doubles as the cwd for a relative command
    wd = re.search(r"^WorkingDirectory=(\S+)", text, re.M)
    roots = [wd.group(1)] if wd else []
    roots += ["/root/legendarypicks", "/root/legendarypicks/backend", "/root/legendarypicks/scripts"]
    out = []
    for tok in sorted(set(TOKEN.findall(text))):
        raw = tok
        for k, v in env.items():
            tok = tok.replace("$" + k, v).replace("${%s}" % k, v)
        if "$" in tok:
            out.append((raw, tok, "UNEXPANDED VAR"))
            continue
        if os.path.isabs(tok):
            if not os.path.exists(tok):
                out.append((raw, tok, "MISSING"))
            continue
        if not any(os.path.exists(os.path.join(r, tok)) for r in roots):
            out.append((raw, tok, "MISSING"))
    if out:
        print("\n== %s" % name)
        for raw, tok, why in out:
            print("   %-40s -> %-60s %s" % (raw, tok, why))
    return len(out)

bad = 0
for t in targets:
    bad += check(t, open(t, errors="replace").read())
if ct:
    bad += check("root crontab", ct)
print("\n%d unresolved command target(s) in host config" % bad)
raise SystemExit(1 if bad else 0)
