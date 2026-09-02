# FanDuel API contract probe — 2026-08-25

## Answer

**Not determinable from this host.** The normal FanDuel sportsbook web app
returned a CloudFront `403` on the first direct request. Per HARD LIMITS item 1,
the investigation stopped immediately: there was no retry, header or TLS
spoofing, proxy, relay, alternate egress, state-host sweep, or guessed API call.

Consequently, the direct FanDuel API question remains unresolved. The refusal
is **not** evidence that the markets are absent. However, an offline audit of
seven already-existing RotoWire captures found 2,796 `fanduel-sb` player-prop
rows and zero soccer rows of any kind. That is a clean negative in the retained
secondary evidence, but it is not proof that RotoWire mirrors FanDuel's entire
board.

Per fixture:

| Fixture | Requested player-stat markets found |
|---|---|
| CF Monterrey vs Chicago Fire — 2026-08-26 00:30 UTC | None in seven local `fanduel-sb` captures; direct FanDuel board unknown |
| Club Leon vs Real Salt Lake — 2026-08-26 02:30 UTC | None in seven local `fanduel-sb` captures; direct FanDuel board unknown |
| Deportivo Toluca vs Austin FC — 2026-08-27 00:30 UTC | None in seven local `fanduel-sb` captures; direct FanDuel board unknown |
| Club America vs Columbus Crew — 2026-08-27 02:45 UTC | None in seven local `fanduel-sb` captures; direct FanDuel board unknown |

## Offline corroboration after the hard stop

No additional network request was made. The retained files
`backend/data/rotowire-archive/rotowire-2026-08-{19..25}.json.gz` were read
offline. For each prop, the audit required an actual line whose exact
`book == "fanduel-sb"`, then joined `prop.marketID -> markets.marketID` and
`prop.entities[] -> entities.entityID -> events.eventID`. It did not classify
by a loose name substring.

| Capture | FanDuel-labeled player props | Soccer | Any of the four fixtures |
|---|---:|---:|---:|
| 2026-08-19 | 445 | 0 | 0 |
| 2026-08-20 | 458 | 0 | 0 |
| 2026-08-21 | 335 | 0 | 0 |
| 2026-08-22 | 339 | 0 | 0 |
| 2026-08-23 | 403 | 0 | 0 |
| 2026-08-24 | 431 | 0 | 0 |
| 2026-08-25 | 385 | 0 | 0 |
| **Total** | **2,796** | **0** | **0** |

The August 25 FanDuel-labeled population was WNBA 176, NFL 135, CFB 57,
and MLB 17. Thus the relay was demonstrably carrying FanDuel lines while
carrying no FanDuel soccer market list. This supports **no player-stat props in
the available secondary feed**. It does not upgrade the direct answer to a
FanDuel-API “no,” because completeness of the relay against FanDuel was not
established.

## Working requests

None. No request reached a FanDuel content or event payload.

The one controlled command-line request was:

```bash
curl --max-time 20 -sS -D - -o /dev/null \
  -w '\nFINAL status=%{http_code} url=%{url_effective} bytes=%{size_download}\n' \
  'https://sportsbook.fanduel.com/'
```

Observed response:

```text
HTTP/2 403
content-type: text/html
content-length: 5739
server: CloudFront
x-cache: Miss from cloudfront

FINAL status=403 url=https://sportsbook.fanduel.com/ bytes=5739
```

## Parameter contract and bundle

No parameter contract was recovered and there is no bundle URL to cite. The
document containing the `<script src=...>` tags was itself denied, so reading a
request constructor from FanDuel's JavaScript was impossible without bypassing
the refusal. The previously tried `_ak=FhMFpcPWXMeyZxOx` value from the task
brief was not reused, and no parameters were guessed.

## Complete request ledger

| # | Request | Status | Result and decision |
|---:|---|---:|---|
| 1 | Browser-tool open of `GET https://sportsbook.fanduel.com/` | Not exposed by that tool | No readable document or response metadata was returned. No contract evidence was obtained. |
| 2 | Direct normal `GET https://sportsbook.fanduel.com/` using the copy-pasteable curl command above | `403` | CloudFront refusal. HARD LIMITS item 1 triggered; all network investigation stopped. |

There were no requests to PrizePicks, DraftKings, FanDuel state hosts,
`sbapi.*`, proxies, relays, or third-party mirrors. The companion probe is
`/tmp/claude-0/-root/2e2fb54f-bafb-4eb9-a810-09f61cc5d7a8/scratchpad/fanduel_probe.py`.
It defaults to printing the recorded result and never performs network I/O
unless explicitly invoked with `--live`; `--archives` reproduces the offline
seven-capture audit. It has no retry or bypass behavior.
