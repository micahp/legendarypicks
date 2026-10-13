# DRAFT: per-IP rate limit on LP's public `/api/` (2026-10-07)

Status: **applied in log-only mode 2026-10-07 17:32 CDT** (Micah's go). Backup of the site file:
`/root/legendarypicks.xyz.conf.bak-20261007-173216`. The secret is `LP_API_BYPASS` in `~/.hermes/.env`
and in `/etc/nginx/conf.d/lp-api-ratelimit.conf` (mode 640). Verified: 400 requests in 8 s from
127.0.0.2 all served, 255 `dry run` lines logged; the same burst with the header logged 0.
Those test lines (client 127.0.0.2, path `/api/__ratelimit_probe`) are ours: exclude them when reading
the log. Not yet enforced. Micah asked for the draft
after a check found nothing in front of LP: no CDN, no nginx limits, no IP rules, and `/api/`
reachable by anyone.

## Why a rate limit and not a datacenter block

A datacenter block would also stop search crawlers, link previews, and any future customer of
the prop-outcome data API (Phase 2) calling from a server. A per-IP rate limit only stops
hammering, wherever it comes from.

## What real traffic looks like (nginx access logs, 2026-09-23 to 2026-10-07)

10,435 `/api/` requests. A normal page load fans out, so real users burst hard:

| who | peak | what |
|---|---|---|
| 90.96.190.177 | 67 requests in 1 s, 73 in 1 min | `/api/props/history` fan-out from one props page |
| 172.56.88.152 (T-Mobile, iPhone) | 26 in 1 s | games lists across leagues on one load |
| 5.252.52.108 (this server) | 53 in 1 min | our own SSR, tunnels and tests: exempt |
| cloud scanners (Alibaba, GCP, Azure) | up to 143 refusals at 1 r/s | mostly `/.env` and Vite probes on the site root |

Carrier IPs (T-Mobile and others) are shared by many phones, so the per-IP allowance has to be
generous.

## Replay: the same two weeks through candidate limits

Leaky bucket replayed per IP at 1-second resolution, this server and loopback excluded
(10,364 requests, 316 IPs):

| rate | burst | real requests refused |
|---|---|---|
| **3 r/s** | **120** | **0** |
| 3 r/s | 60 | 9, all from the 67-per-second props page |
| 2 r/s | 60 | 10, same page |
| 1 r/s | 30 | 543 from 28 IPs |

3 r/s with a burst of 120 refuses nothing seen in two weeks. It still caps one IP at about
180 requests a minute after the burst, or ~10,800 an hour, instead of whatever the backend can
serve.

## Home and other devices whose IP changes

A home connection's IP changes whenever the ISP reassigns it, and phones change IP between Wi-Fi and
cellular, so an IP allowlist entry for them goes stale. Two things cover them instead:

- **Browsing needs nothing.** The replay refused 0 real requests, and a person on the site never gets
  near 120 at once plus 3 a second.
- **Scripts from home** (a scraper, a notebook, a backfill) send the header `X-LP-Bypass: <secret>`,
  which exempts the request from any IP. The secret lives only in the conf.d file on the server and
  in your home box's environment, never in git. Rotate it by editing that one line and reloading.

Fixed servers (this one and 89.117.145.232) are allowlisted by IP, since their addresses don't change.

## The change

1. New file `/etc/nginx/conf.d/lp-api-ratelimit.conf` (http context; only LP references the zone):

```nginx
# Legendary Picks /api/ per-IP rate limit (http context). Used only by legendarypicks.xyz.conf.
# Exempt (an empty key is never limited): loopback, our two servers, and any request carrying
# the bypass header. The header works from any IP, so it covers home and phones whose address changes.
geo $lp_api_exempt_ip {
    default         0;
    127.0.0.1       1;
    ::1             1;
    5.252.52.108    1;   # this server
    89.117.145.232  1;   # Micah's other server
}
map $http_x_lp_bypass $lp_api_bypass {
    default                 0;
    "<SECRET, set on the box only, never in git>"  1;
}
map "$lp_api_exempt_ip:$lp_api_bypass" $lp_api_key {
    "0:0"   $binary_remote_addr;
    default "";
}
limit_req_zone $lp_api_key zone=lp_api:10m rate=3r/s;
```

2. In `/etc/nginx/sites-available/legendarypicks.xyz.conf`, at the top of BOTH
   `location = /api/nfl/mock-draft/pool` and `location /api/`:

```nginx
        limit_req zone=lp_api burst=120 nodelay;
        limit_req_status 429;
        limit_req_dry_run on;
```

Validated with `nginx -t` on a scratch copy of the full live config (2026-10-07): syntax ok.

## Rollout

1. Apply with `limit_req_dry_run on`, then `nginx -t && systemctl reload nginx`. Nothing is
   refused; nginx logs each would-be refusal to `/var/log/nginx/error.log` as
   `limiting requests, dry run`.
2. After a few days, including an NFL Sunday, read who would have been refused:
   `grep "dry run" /var/log/nginx/error.log | grep -o 'client: [0-9a-f.:]*' | sort | uniq -c | sort -rn`.
   If a real user appears, raise the burst before enforcing.
3. Enforce: delete the two `limit_req_dry_run on;` lines, `nginx -t`, reload. Refused requests
   get HTTP 429.

Rollback at any step: remove the three lines from both locations and the conf.d file, `nginx -t`,
reload.

## Not covered

- Requests to the Next.js pages (port 3100) are not limited, only `/api/` on 8100.
- An IP rotating across many addresses gets 120 + 3 r/s per address. Stopping that takes
  API keys for the data API, which is a Phase 2 decision.
- `docs/nginx-legendarypicks.xyz.conf` and `docs/legendarypicks.xyz.conf` are out of date with
  the live file (port 3000/8000 vs the live 3100/8100, no TLS block). This draft is written
  against the live file.
