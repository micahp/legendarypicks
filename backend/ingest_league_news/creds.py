"""Credentials: Bluesky/X keys from the environment or /root/.hermes/.env."""
import json
import os
import sys
import urllib.request

BLUESKY_PDS = "https://bsky.social"

# The secret has been spelled more than one way. `BLSKY_PASS` is what is actually
# in /root/.hermes/.env (2026-08-17); `BSKY_APP_PASSWORD` is what this code asked
# for first. Reading only one spelling is how a credential that IS present reads
# as absent, and the failure is silent -- the collector would just keep reporting
# "no credential" with the value sitting right there. Accept the known spellings
# and SAY which one was used, so the mismatch is visible instead of fatal.
_BSKY_PASS_KEYS = ("BSKY_APP_PASSWORD", "BSKY_PASS", "BLSKY_PASS")

_BSKY_HANDLE_KEYS = ("BSKY_HANDLE", "BLSKY_HANDLE")

def _env_or_hermes(keys):
    """First of `keys` set in the environment, else in the shared .env.

    Returns (key_name, value) so the caller can report WHICH spelling matched.
    Same .env convention as _core._deepseek_key.
    """
    for k in keys:
        v = os.environ.get(k)
        if v:
            return k, v.strip()
    try:
        with open("/root/.hermes/.env") as f:
            lines = f.readlines()
    except Exception:
        return None, None
    for k in keys:                       # key order is priority, not file order
        for line in lines:
            if line.startswith(k + "="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return k, v
    return None, None

def _bsky_credential():
    """(handle, secret) or (None, None).

    Prefer an APP PASSWORD over the account password: it is scoped, revocable
    from the Bluesky UI, and cannot change the account. Generate one at
    Settings -> Privacy and Security -> App Passwords. `createSession` accepts
    either, so this works regardless -- but a leaked app password costs a
    revocation and a leaked account password costs the account.
    """
    hkey, handle = _env_or_hermes(_BSKY_HANDLE_KEYS)
    pkey, secret = _env_or_hermes(_BSKY_PASS_KEYS)
    if handle and secret:
        print("  bluesky: credential from %s / %s" % (hkey, pkey))
    return handle, secret

_BSKY_TOKEN = {"jwt": None, "tried": False}

def _bsky_token():
    """An accessJwt for the authenticated search path, or None.

    Why this exists: `app.bsky.feed.searchPosts` refuses UNAUTHENTICATED callers
    at the CDN edge (a BunnyCDN 403 page, not an ATProto error). Measured
    2026-08-17 from this box: with an Authorization header the same request
    returns `401 {"error":"BadJwt"}` -- a real ATProto response, so the request
    passes the edge and is auth-checked. The endpoint is gated, not lost.

    One session per process, cached. The token is short-lived, and every job that
    uses it is a single short run, so there is no refresh path here on purpose --
    a run that outlives its token should fail and be seen, not silently re-auth
    in a loop.

    NEVER logged, printed, or put in an error message.
    """
    if _BSKY_TOKEN["tried"]:
        return _BSKY_TOKEN["jwt"]
    _BSKY_TOKEN["tried"] = True
    handle, secret = _bsky_credential()
    if not (handle and secret):
        missing = []
        if not handle:
            missing.append("handle (%s)" % "/".join(_BSKY_HANDLE_KEYS))
        if not secret:
            missing.append("password (%s)" % "/".join(_BSKY_PASS_KEYS))
        print("  bluesky: missing %s — searchPosts is gated to unauthenticated "
              "callers, so this run collects nothing from it. Set them in "
              "/root/.hermes/.env (an app password, not the account password)."
              % " and ".join(missing), file=sys.stderr, flush=True)
        return None
    body = json.dumps({"identifier": handle, "password": secret}).encode()
    req = urllib.request.Request(
        BLUESKY_PDS + "/xrpc/com.atproto.server.createSession", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            _BSKY_TOKEN["jwt"] = json.loads(r.read()).get("accessJwt")
    except Exception as exc:
        detail = ""
        try:
            detail = " — " + exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        # `handle` is not secret; the password is, and is never in this string.
        print("  bluesky: createSession failed for %s: %s: %s%s"
              % (handle, type(exc).__name__, exc, detail),
              file=sys.stderr, flush=True)
        return None
    print("  bluesky: authenticated as %s" % handle)
    return _BSKY_TOKEN["jwt"]

# Stop asking after this many consecutive refusals. A publisher that has refused
# three times in a row is not having a bad moment.
#
# Measured 2026-08-17, from this box, same IP, same second:
#
#     public.api.bsky.app  app.bsky.actor.getProfile    200
#     public.api.bsky.app  app.bsky.feed.searchActors   200
#     public.api.bsky.app  app.bsky.feed.getAuthorFeed  200
#     public.api.bsky.app  app.bsky.feed.searchPosts    403   <-- and api.bsky.app too
#
# So this is NOT a rate block and NOT our IP: a volume block refuses the host,
# and every other endpoint on that host answers. The 403 body is a BunnyCDN edge
# page rather than Bluesky's JSON error envelope -- the request never reaches
# the API.
#
# It is gated on being UNAUTHENTICATED, and that distinction is the whole point.
# Measured the same day, same box:
#
#     api.bsky.app  searchPosts, no header          -> 403  (Bunny edge page)
#     api.bsky.app  searchPosts, Authorization: ... -> 401  {"error":"BadJwt"}
#     bsky.social   com.atproto.server.createSession -> 401 (fake creds; endpoint live)
#
# A malformed token gets a real ATProto error, which means the request PASSES
# the edge and is auth-checked by the API. So Bluesky search is not lost to us;
# it needs a session. `createSession` with an app password -> accessJwt ->
# `Authorization: Bearer` on this call. That needs an account and a credential,
# which is Micah's decision, so it is written up rather than done here.
#
# Until then this endpoint refuses every unauthenticated request instantly, so
# retrying it is not perseverance -- it was 300 pointless requests a day aimed
# at somebody hosting us for free.
#
# (Line 226's host swap on 2026-08-06 was this same 403 answered by moving hosts
# without first establishing what it meant. Both hosts refuse it unauthenticated.)
_BSKY_GIVE_UP = 3

def _x_key():
    return os.environ.get("LP_XAPI_KEY", "").strip()
