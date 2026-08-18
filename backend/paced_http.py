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


def reset_host_budget():
    """Forget what has been spent. For tests, and after a deliberate long wait."""
    _host_spend.clear()


def _charge(url, budget, cooldown):
    if not budget or budget <= 0:
        return
    host = urllib.parse.urlsplit(url).netloc
    if _host_spend.get(host, 0) >= budget:
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
                 host_budget=None, host_cooldown=None):
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
        self._last_request_at = 0.0
        self._memory = {}
        # Bound the cache directory: swept every N writes (see _sweep).
        self._writes_since_sweep = 0
        self._sweep_every = 500

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
        for name in names:
            if not name.endswith(".json") or len(name) != 37:
                continue    # 32 hex chars + ".json" — not one of ours
            path = os.path.join(self.cache_dir, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                continue    # a concurrent reader or a vanished file is not an error

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
            _charge(url, self.host_budget, self.host_cooldown)
            self._throttle()
            try:
                request = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as exc:
                if exc.code in RETRYABLE and wait is not None:
                    time.sleep(wait)
                    continue
                raise
            except (OSError, json.JSONDecodeError):
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
            _charge(url, self.host_budget, self.host_cooldown)
            self._throttle()
            try:
                request = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as r:
                    return r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code in RETRYABLE and wait is not None:
                    time.sleep(wait)
                    continue
                raise
            except OSError:
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
            return hit[1]
        on_disk = self._read_disk(url, ttl)
        if on_disk is not None:
            self._memory[url] = (now + ttl, on_disk)
            return on_disk
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
            raise
        self._memory[url] = (now + ttl, data)
        self._write_disk(url, data)
        return data
