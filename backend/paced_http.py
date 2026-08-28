"""One paced, budgeted, cached HTTP GET, instead of six near-copies of it.

Six modules had each written their own `_throttle` / `RETRY_WAITS` / `_RETRYABLE`
block, and `espn_client.py` -- the one every serving path and the heaviest batch
job go through -- had none at all until 2026-08-04. That asymmetry is what let
`roster_sync.py` fire 128 requests back to back and trip ESPN's wall: the
discipline existed in the repo, just not where the requests were.

Three mechanisms, each of which had to be learned the hard way:

**Pacing.** A minimum gap between requests. Per-caller, because the right gap is
a property of the publisher: nhle.com has taken ~1,748 unpaced requests without
complaint, ESPN has not.

**A per-host budget.** Pacing alone does not describe ESPN's wall. Measured at
identical 1s spacing on 2026-08-04, `site.web.api` served 128 requests clean
while `sports.core` refused at ~119 -- both ~60 requests/minute, so no rate
ceiling explains either. The limit is a COUNT per host, about 100. The budget is
shared process-wide and keyed on host, because that is what the publisher counts;
two callers hitting one host spend one budget.

**A disk cache.** In-process caches die with the process, so their TTLs never
survive a run and every invocation re-pays for bytes it already had. Cache hits
do not charge the budget, which is what makes a refused batch job resumable for
free rather than restartable from zero.

All three are opt-in. A serving path must not pause and must not answer from an
hours-old payload, so the defaults do nothing.

    fetch = Fetcher(min_interval=0.5, retry_waits=(5.0, 20.0, 60.0))
    doc = fetch.json(url)
"""

from __future__ import annotations

import json
import collections
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_HDRS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "Chrome/124 Safari/537.36")
}

# 403 and 429 are in here because an upstream refusal is temporary: measured
# 2026-08-04, both ESPN hosts refused and were serving again inside ten minutes.
# Waiting one out beats failing the caller, so the ladder is minutes not seconds.
RETRYABLE = frozenset({403, 429, 500, 502, 503, 504})

# Shared across every Fetcher in the process, because the publisher counts per
# host and does not care which of our modules asked.
HOST_BUDGET = int(os.environ.get("LP_HTTP_HOST_BUDGET", "100"))
HOST_COOLDOWN = float(os.environ.get("LP_HTTP_HOST_COOLDOWN", "60"))
_host_spend: dict[str, int] = {}

# ── the burst rate, measured ──────────────────────────────────────────────────
#
# ANSWERED 2026-08-19 from the spend log, 27,801 ESPN requests over 25 hours.
# What precedes a 403 versus what precedes a 200 on the healthy host:
#
#     requests in the 60s   before a 403 : median   63    before a 200 :   36
#     requests in the 5min  before a 403 : median  311    before a 200 :  141
#     requests in the 1h    before a 403 : median 1238    before a 200 : 1266   FLAT
#
# **The hour is flat. The minute is not.** So the publisher's limit is a SHORT
# WINDOW RATE, not the per-host request COUNT that HOST_BUDGET above models and
# not an hourly budget. See docs/DESIGN-request-budget.md §1b.
#
# The offender is one job: `ingest_scoreboards.py` is 71% of all ESPN traffic,
# and its heaviest runs fire 94-142 requests in 11-26 seconds, over 500/min,
# roughly 8x the rate where refusals begin.
#
# 50 per 60s is deliberately below the 63 where 403s concentrate and above the
# 36 that precedes a typical success. It is a first setting, not a known
# threshold: the measurement establishes the SHAPE over one day and does not
# establish where refusals become certain. Re-measure before tightening.
HOST_RATE = int(os.environ.get("LP_HTTP_HOST_RATE", "50"))
RATE_WINDOW = float(os.environ.get("LP_HTTP_RATE_WINDOW", "60"))
_host_recent: dict[str, "collections.deque"] = {}


def reset_host_budget():
    """Forget what has been spent. For tests, and after a deliberate long wait."""
    _host_spend.clear()
    _host_recent.clear()


def _pace_rate(url, on_exhausted="sleep"):
    """Hold the per-host short-window rate. Returns the seconds waited.

    Process-wide, like `_host_spend`, because the publisher counts per host and
    not per module. **It does NOT coordinate across processes**, so five jobs
    each pacing at HOST_RATE can still show the host 5x that. That is the same
    per-process-versus-per-host flaw the count budget has, and it is left open
    on purpose: 71% of the traffic is a single job, so pacing each process
    removes most of the burst without the shared-state machinery whose last
    attempt was reverted. Whether the rest matters is a question for the next
    day of spend-log data, not a guess to build against now.

    `on_exhausted` carries the same meaning as in `_charge`: a batch job may
    wait, a request handler may NOT. Getting that backwards is what made prod
    sleep 46 minutes on 2026-08-18.
    """
    if not HOST_RATE or HOST_RATE <= 0:
        return 0.0
    host = urllib.parse.urlsplit(url).netloc
    now = time.time()
    seen = _host_recent.setdefault(host, collections.deque())
    while seen and now - seen[0] >= RATE_WINDOW:
        seen.popleft()
    waited = 0.0
    if len(seen) >= HOST_RATE:
        wait = RATE_WINDOW - (now - seen[0])
        if on_exhausted == "refuse":
            raise BudgetExhausted(
                f"{host} has taken {len(seen)} requests in the last "
                f"{RATE_WINDOW:.0f}s; refusing rather than pausing {wait:.1f}s, "
                f"because this caller has someone waiting.")
        if wait > 0:
            time.sleep(wait)
            waited = wait
        now = time.time()
        while seen and now - seen[0] >= RATE_WINDOW:
            seen.popleft()
    seen.append(now)
    return waited


# ── the spend log ─────────────────────────────────────────────────────────────
#
# Every number we have about ESPN's limit except the response cap is INFERRED
# from behaviour, twice, and both times another explanation was available. See
# docs/DESIGN-request-budget.md §1: there are two different limits both called
# "100", and the last attempt to build a cross-process budget was reverted
# because of the confusion between them.
#
# So before any more machinery: write down what we actually spend. One append
# per request, no behaviour change, nothing to revert. It turns the questions
# that are currently guesses into queries -- above all **does a 403 correlate
# with a request count, or with a time of day, or with nothing?**, which is the
# question that decides whether a shared counter is the right machine at all.
#
# A plain append-only JSONL file rather than SQLite on purpose: 18 timers write
# this concurrently, and an O_APPEND write below PIPE_BUF is atomic on Linux,
# so there is no lock to contend and no job can be wedged behind one.
_PROD_SPEND_LOG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "http-spend.jsonl")
SPEND_LOG = os.environ.get("LP_HTTP_SPEND_LOG", _PROD_SPEND_LOG)

# Who is spending. argv[0] is the job, and the whole point is telling eighteen
# timers apart in one file.
#
# `python -m pkg` sets argv[0] to the package's `__main__.py`, so a plain
# basename collapses EVERY `-m` invocation into one label. Measured 2026-08-19:
# 3,043 ESPN requests, 11% of the day's traffic, all logged as `__main__.py`
# across 395 distinct minutes, and unattributable. `python -m pytest` lands in
# the same bucket as the ingest packages. The 08-18 package split made this
# worse by turning two scripts into `-m` targets.
#
# So resolve `__main__.py` to the package that owns it, which is the directory
# name, and name the test runner explicitly.
def _who():
    argv0 = (sys.argv[0] if sys.argv else "") or "python"
    base = os.path.basename(argv0)
    if base != "__main__.py":
        return base
    pkg = os.path.basename(os.path.dirname(os.path.abspath(argv0)))
    if pkg in ("pytest", "_pytest"):
        return "pytest"
    return pkg or "__main__.py"


_PROCESS = _who()


def _path_family(parts):
    """A coarse path key, so one league's scoreboard does not become its own row.

    Keeps the leading segments and drops ids and query strings: the question is
    "which endpoint family costs us", not "which game".
    """
    trimmed = [seg for seg in parts.path.split("/") if seg][:5]
    return "/" + "/".join(trimmed)


# A test run is not spend. Measured 2026-08-24: `test_ingest_nba_stats.py` drives
# a mocked urlopen through 403/429/404 against a real NBA core URL, and this
# function recorded all 8 attempts as if they had left the box. They read as a
# live host refusing us, on the exact endpoint this project has documented as
# gated, and I reported them to Micah as the suite hammering a walled endpoint.
# They never happened. The same shape produced 102 phantom 403s to a league named
# `test` in the 08-19 sample, which that analysis had to detect and exclude by
# hand.
#
# So the PRODUCTION log records production traffic and nothing else. A log that
# mixes simulated events with real ones will eventually be read as if all of them
# were real, and the reader cannot tell which is which from the row.
#
# Keyed on the destination, not on the caller: a test that points SPEND_LOG
# somewhere else, by monkeypatch or by LP_HTTP_SPEND_LOG, is measuring on purpose
# and still gets its rows. Only the default production path is protected. The
# suite's genuinely-live calls stop appearing there too, which is the intended
# trade: to attribute those, run the suite with a probe that patches urlopen.
_IS_TEST_RUN = _PROCESS == "pytest"


def record_spend(url, status, cached=False, note=""):
    """Append one line describing a request. NEVER raises: this is measurement.

    A logging failure must not take down a fetch. If the directory is missing
    or the disk is full we lose the record, which is strictly better than
    losing the request.
    """
    if _IS_TEST_RUN and os.path.abspath(SPEND_LOG) == os.path.abspath(_PROD_SPEND_LOG):
        return
    try:
        parts = urllib.parse.urlsplit(url)
        line = json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "host": parts.netloc,
            "path": _path_family(parts),
            "status": status,
            "cached": bool(cached),
            "proc": _PROCESS,
            "pid": os.getpid(),
            "note": note,
        }, separators=(",", ":"))
        with open(SPEND_LOG, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


class BudgetExhausted(RuntimeError):
    """The per-host count is spent and this caller must not wait it out."""


def _charge(url, budget, cooldown, on_exhausted="sleep"):
    """Spend one request against the host's count.

    `on_exhausted` is the difference between a batch job and a page load, and
    getting it wrong is what broke the scoreboard. The default, "sleep", is
    right for an ingest: it has nobody waiting and the work is worth the minute.
    Inside a request handler it is catastrophic -- measured on prod 2026-08-18,
    46 minutes of uptime produced 46 sixty-second sleeps, 38 of them in one
    seven-second window, because this check is not guarded and every caller in
    flight sleeps its own minute when the process crosses the ceiling. A serving
    path passes "refuse" and gets an exception it can degrade from, which is the
    behaviour the scores ladder (DB, then Bovada) was built for.
    """
    if not budget or budget <= 0:
        return
    # Request handlers are already protected by `_pace_rate`, the measured
    # short-window limit above. A cumulative process-lifetime counter has no
    # time window and therefore never recovers in a long-running API process:
    # after its 100th request every later page load was refused until deploy or
    # restart. Keep the count/cooldown circuit for bounded batch jobs, but do
    # not turn normal process uptime into an outage for serving paths.
    if on_exhausted == "refuse":
        return
    host = urllib.parse.urlsplit(url).netloc
    if _host_spend.get(host, 0) >= budget:
        if on_exhausted == "refuse":
            raise BudgetExhausted(
                f"{host} has taken {budget} requests from this process; refusing "
                f"rather than pausing {cooldown:.0f}s, because this caller has "
                f"someone waiting. The budget is a count, not an error.")
        # SAY SO. This used to sleep a silent minute: no message, no traceback, a job
        # that simply stopped producing output partway through and resumed later for no
        # visible reason. Diagnosing it meant knowing this line existed. A pause nobody
        # can attribute is worse than a slow job -- it gets misread as a hang, and the
        # usual response is to kill the run and lose the work.
        print(f"paced_http: {host} has taken {budget} requests from this process; "
              f"pausing {cooldown:.0f}s before the next one. This is the per-host count "
              f"budget, not an error. Fewer requests is the only real fix: use a bulk "
              f"endpoint, or set_disk_cache() so a re-run costs nothing.",
              file=sys.stderr, flush=True)
        time.sleep(cooldown)
        _host_spend[host] = 0
    _host_spend[host] = _host_spend.get(host, 0) + 1


class Fetcher:
    """A GET with pacing, retries, an optional per-host budget and disk cache."""

    def __init__(self, min_interval=0.0, retry_waits=(5.0, 30.0, 120.0),
                 headers=None, timeout=30, cache_dir="", cache_ttl=43200,
                 host_budget=None, host_cooldown=None, on_exhausted="sleep"):
        self.min_interval = float(min_interval or 0)
        self.retry_waits = tuple(retry_waits or ())
        self.headers = headers or DEFAULT_HDRS
        self.timeout = timeout
        self.cache_dir = cache_dir or ""
        self.cache_ttl = float(cache_ttl or 0)
        # None means "use the process-wide default"; 0 means "this publisher has
        # no measured count limit" -- nhle.com, for one, where applying ESPN's
        # number would add cooldowns for a wall nobody has observed.
        self.host_budget = HOST_BUDGET if host_budget is None else int(host_budget)
        self.host_cooldown = (HOST_COOLDOWN if host_cooldown is None
                              else float(host_cooldown))
        # "sleep" (a batch job may wait) or "refuse" (a request handler may not).
        # See _charge -- this is the setting whose default cost the scoreboard.
        self.on_exhausted = on_exhausted
        self._last_request_at = 0.0
        self._memory = {}
        # Bound the cache directory: swept every N writes (see _sweep).
        self._writes_since_sweep = 0
        self._sweep_every = 500
        self.cache_max_bytes = float(
            os.environ.get("LP_ESPN_CACHE_MAX_BYTES", "536870912") or 0
        )

    # ── cache ────────────────────────────────────────────────────────────
    def _path(self, url):
        import hashlib
        return os.path.join(
            self.cache_dir, hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")

    def _read_disk(self, url, ttl=None):
        """`ttl` is the caller's freshness requirement for THIS url.

        Without it the disk layer answered every read against `cache_ttl` — 12
        hours by default — so a scoreboard asking for a 20-second cache would
        have been handed a half-day-old score the moment a disk cache was
        configured. The per-call ttl is the tighter contract and wins; a caller
        that names none still gets the instance default, which is what the bulk
        ingest scripts rely on for a free re-run.
        """
        if not self.cache_dir or self.cache_ttl <= 0:
            return None
        window = self.cache_ttl if ttl is None else min(float(ttl), self.cache_ttl)
        if window <= 0:
            return None
        try:
            if time.time() - os.path.getmtime(self._path(url)) > window:
                return None
            with open(self._path(url)) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            # A corrupt or absent entry is a miss, never an error -- the caller's
            # job is to get the data, not to care where it came from.
            return None

    def _read_disk_stale(self, url):
        """Read a valid cached payload regardless of age for outage fallback."""
        if not self.cache_dir:
            return None
        try:
            with open(self._path(url)) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _sweep(self):
        """Drop entries older than `cache_ttl`. Nothing else ever deletes one.

        This cache had no eviction at all: the two directories on the host had
        grown to 100MB and 134MB, and a 96MB copy of one is what got swept into
        git and took the image to 7.45GB. Re-enabling an unbounded cache would
        just re-run that.

        Sampled rather than run on every write — the cost is a directory listing,
        and the bound only has to hold over hours, not milliseconds. Deletion is
        confined to files this class wrote (its own hashed `.json` names) inside
        its own cache_dir; anything else in there is left alone.
        """
        cutoff = time.time() - self.cache_ttl
        try:
            names = os.listdir(self.cache_dir)
        except OSError:
            return
        survivors = []
        for name in names:
            if not name.endswith(".json") or len(name) != 37:
                continue    # 32 hex chars + ".json" — not one of ours
            path = os.path.join(self.cache_dir, name)
            try:
                stat = os.stat(path)
                if stat.st_mtime < cutoff:
                    os.remove(path)
                else:
                    survivors.append((stat.st_mtime, stat.st_size, path))
            except OSError:
                continue    # a concurrent reader or a vanished file is not an error

        # Age alone does not bound a cache — a busy day inside one ttl window can
        # still fill a disk. Docker cannot size-cap a `local` volume on overlay2
        # without filesystem quotas, so the ceiling is enforced here: oldest
        # entries go first until the directory is back under the limit.
        if self.cache_max_bytes <= 0:
            return
        total = sum(size for _mtime, size, _path in survivors)
        if total <= self.cache_max_bytes:
            return
        survivors.sort()                      # oldest first
        for _mtime, size, path in survivors:
            if total <= self.cache_max_bytes:
                break
            try:
                os.remove(path)
                total -= size
            except OSError:
                continue

    def _write_disk(self, url, data):
        if not self.cache_dir:
            return
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            self._writes_since_sweep += 1
            if self._writes_since_sweep >= self._sweep_every:
                self._writes_since_sweep = 0
                self._sweep()
            tmp = self._path(url) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._path(url))   # atomic: no reader sees half a file
        except OSError:
            pass

    # ── request ──────────────────────────────────────────────────────────
    def _throttle(self):
        if self.min_interval <= 0:
            return
        gap = time.time() - self._last_request_at
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_request_at = time.time()

    def fetch(self, url, retry=True):
        """One request, retrying an upstream refusal on a widening wait.

        `retry=False` gives up on the first refusal. Callers with a fallback use
        it: waiting out a 155s ladder while holding a perfectly good stale
        payload -- and a user -- is worse than answering immediately.
        """
        for wait in (*(self.retry_waits if retry else ()), None):
            _pace_rate(url, self.on_exhausted)
            _charge(url, self.host_budget, self.host_cooldown, self.on_exhausted)
            self._throttle()
            try:
                request = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as r:
                    payload = json.loads(r.read().decode())
                record_spend(url, getattr(r, "status", 200))
                return payload
            except urllib.error.HTTPError as exc:
                # A refusal is the most valuable line in the log: it is the one
                # that says whether a 403 tracks a request count or nothing.
                record_spend(url, exc.code, note="retrying" if
                             (exc.code in RETRYABLE and wait is not None) else "raised")
                if exc.code in RETRYABLE and wait is not None:
                    time.sleep(wait)
                    continue
                raise
            except (OSError, json.JSONDecodeError) as exc:
                record_spend(url, 0, note=type(exc).__name__)
                if wait is not None:
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError(f"{url} failed: retries exhausted")

    def fetch_text(self, url, retry=True):
        """One request, returning the raw body as text.

        `fetch` json-decodes, which is wrong for RSS and XML. Added 2026-08-10
        for the Nitter mirror; the RSS collectors were making bare urlopen calls
        with no pacing, no retry and no cache at all.
        """
        for wait in (*(self.retry_waits if retry else ()), None):
            _pace_rate(url, self.on_exhausted)
            _charge(url, self.host_budget, self.host_cooldown, self.on_exhausted)
            self._throttle()
            try:
                request = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as r:
                    body = r.read().decode("utf-8", "replace")
                record_spend(url, getattr(r, "status", 200))
                return body
            except urllib.error.HTTPError as exc:
                record_spend(url, exc.code, note="retrying" if
                             (exc.code in RETRYABLE and wait is not None) else "raised")
                if exc.code in RETRYABLE and wait is not None:
                    time.sleep(wait)
                    continue
                raise
            except OSError as exc:
                record_spend(url, 0, note=type(exc).__name__)
                if wait is not None:
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError(f"{url} failed: retries exhausted")

    def text(self, url, ttl=None):
        """Cached text GET. Shares the disk cache, wrapped so it stays JSON."""
        now = time.time()
        ttl = self.cache_ttl if ttl is None else float(ttl)
        key = "text:" + url
        hit = self._memory.get(key)
        if hit and hit[0] > now:
            return hit[1]
        on_disk = self._read_disk(key)
        if isinstance(on_disk, dict) and "text" in on_disk:
            self._memory[key] = (now + ttl, on_disk["text"])
            return on_disk["text"]
        body = self.fetch_text(url)
        self._write_disk(key, {"text": body})
        self._memory[key] = (now + ttl, body)
        return body

    def json(self, url, ttl=None):
        """Cached GET. `ttl` overrides the in-memory lifetime for this URL."""
        now = time.time()
        ttl = self.cache_ttl if ttl is None else float(ttl)
        hit = self._memory.get(url)
        if hit and hit[0] > now:
            # Logged too: a request we did NOT make is the cheapest lever we
            # have, and the hit rate is the number that says whether caching
            # or a budget is the better next move.
            record_spend(url, 200, cached=True, note="memory")
            return hit[1]
        on_disk = self._read_disk(url, ttl)
        if on_disk is not None:
            self._memory[url] = (now + ttl, on_disk)
            record_spend(url, 200, cached=True, note="disk")
            return on_disk
        # Only interactive readers may use stale-on-error. A batch publisher
        # must fail instead of treating an expired response as fresh input.
        stale_disk = (self._read_disk_stale(url)
                      if self.on_exhausted == "refuse" else None)
        try:
            # Retry hard only when failing is the alternative. With a stale
            # payload in hand the ladder is pure latency on a request somebody
            # is waiting for, so a refusal falls straight through to it.
            data = self.fetch(url, retry=hit is None)
        except Exception:
            # A stale payload beats a stack trace. On 2026-08-04 an ESPN 403 made
            # every scores and standings surface 500 the instant a 30s cache
            # expired, and the page then read "No data available" -- blaming our
            # data for an upstream refusal. `hit` is kept past its expiry for
            # exactly this. With nothing cached the error still propagates:
            # serving invented emptiness would be worse than failing.
            if hit is not None:
                self._memory[url] = (now + min(ttl, 60), hit[1])
                return hit[1]
            if stale_disk is not None:
                self._memory[url] = (now + min(ttl, 60), stale_disk)
                record_spend(url, 200, cached=True, note="stale-disk")
                return stale_disk
            raise
        self._memory[url] = (now + ttl, data)
        self._write_disk(url, data)
        return data
