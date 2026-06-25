# Ephemeral branch previews — Traefik + Cloudflare Tunnel

Self-hosted "preview deploy" per branch. Push/run a branch → get
`https://<branch>.preview.legendarypicks.xyz` running against a fresh clone of prod's DB,
behind auth. Tear it down when done. No SaaS, no monthly bill, runs on your VPS.

## Why this stack

- **Traefik** = dynamic reverse proxy. Containers carry labels; Traefik auto-routes by
  hostname. New preview container → route appears. Tear it down → route gone. Zero config
  edits per branch. It also ships an HTTP API + dashboard, so a GUI/automation layer later
  extends what's already there.
- **Cloudflare Tunnel (`cloudflared`)** instead of a wildcard Let's Encrypt cert:
  - No public ports opened on the VPS — `cloudflared` dials *out* to Cloudflare.
  - **TLS is terminated at Cloudflare's edge**, so there's no cert to issue/renew/manage and
    no DNS-01 token juggling. The whole cert problem from the wildcard-cert approach disappears.
  - Free. No asterisk.

## Architecture

```
browser
  │  https://analytics-backbone.preview.legendarypicks.xyz
  ▼
Cloudflare edge  (terminates TLS, wildcard hostname)
  │  outbound tunnel
  ▼
cloudflared  (container on the VPS)
  │  http://traefik:80   (all *.preview.* sent here)
  ▼
Traefik  (routes by Host header, via docker labels)
  │
  ├─ preview-analytics-backbone   → frontend:3000  + backend  (LP_DB_PATH=clone)
  └─ preview-<other-branch>        → its own containers + its own DB clone
```

Everything below `cloudflared` is plain HTTP on a private docker network. Nothing is exposed
on the host.

## One-time setup

### 1. Create the tunnel
```bash
cloudflared tunnel login                      # browser auth, once
cloudflared tunnel create lp-preview          # prints a TUNNEL_UUID + creds json
```

### 2. Wildcard DNS (Cloudflare dashboard)
Add a **CNAME**, proxied (orange cloud):
```
*.preview.legendarypicks.xyz  →  <TUNNEL_UUID>.cfargotunnel.com
```

### 3. cloudflared ingress (`cloudflared/config.yml`)
```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json
ingress:
  - hostname: "*.preview.legendarypicks.xyz"
    service: http://traefik:80
  - service: http_status:404
```

### 4. Shared network + Traefik + cloudflared (`docker-compose.preview-infra.yml`)
```yaml
networks:
  preview-net:
    name: preview-net          # preview containers join this too

services:
  traefik:
    image: traefik:v3.1
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
      # - --api.dashboard=true        # enable later when building the GUI
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks: [preview-net]
    labels:
      # one basic-auth middleware shared by all previews
      - traefik.http.middlewares.preview-auth.basicauth.users=${PREVIEW_AUTH}

  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --no-autoupdate run
    volumes:
      - ./cloudflared:/etc/cloudflared:ro
    networks: [preview-net]
    depends_on: [traefik]
```
`PREVIEW_AUTH` = output of `htpasswd -nb micah '<password>'` (escape `$` as `$$` in compose).
Bring the infra up once: `docker compose -f docker-compose.preview-infra.yml up -d`.

> Auth alternative: drop the basic-auth middleware and put **Cloudflare Access** in front of
> `*.preview.legendarypicks.xyz` instead — it's already in the path. Either works; basic-auth
> keeps it self-contained.

## Per-branch preview

### Preview compose override (`docker-compose.preview.yml`)
Reuses the prod service definitions; adds labels + the cloned DB. `${BRANCH}` and
`${LP_DB_PATH}` are injected by the script.
```yaml
networks:
  preview-net:
    external: true

services:
  frontend:
    networks: [preview-net]
    labels:
      - traefik.enable=true
      - traefik.http.routers.${BRANCH}.rule=Host(`${BRANCH}.preview.legendarypicks.xyz`)
      - traefik.http.routers.${BRANCH}.middlewares=preview-auth@docker
      - traefik.http.services.${BRANCH}.loadbalancer.server.port=3000
  backend:
    networks: [preview-net]
    environment:
      - LP_DB_PATH=/data/${BRANCH}.db
    volumes:
      - ./backend/data:/data
```

### The script (`scripts/preview`)
```bash
#!/usr/bin/env bash
set -euo pipefail
cmd=$1; branch=$2
proj="preview-$(echo "$branch" | tr '/_' '-')"

case "$cmd" in
  up)
    git worktree add -f ".previews/$branch" "$branch"        # isolated checkout
    # fresh consistent clone of prod DB (prod is READ-only here)
    sqlite3 backend/data/picks.db ".backup 'backend/data/${branch}.db'"
    BRANCH="$branch" LP_DB_PATH="backend/data/${branch}.db" \
      docker compose -p "$proj" \
        -f ".previews/$branch/docker-compose.yml" \
        -f docker-compose.preview.yml up -d --build
    echo "→ https://${branch}.preview.legendarypicks.xyz"
    ;;
  down)
    docker compose -p "$proj" down -v || true
    git worktree remove -f ".previews/$branch" || true
    rm -f "backend/data/${branch}.db"
    echo "torn down: $branch"
    ;;
esac
```

Usage:
```
scripts/preview up analytics-backbone
scripts/preview down analytics-backbone
```

## Resource notes (your VPS has limited RAM)

- Each `up` builds the Next.js image — minutes of CPU/RAM. Build on demand; don't leave
  previews idle.
- Cap to 1–2 live previews at a time. `down` frees everything (containers + DB clone).
- The Traefik + cloudflared infra is light and can stay up permanently.

## Anti-Plane guarantee

Previews run against a **clone** of prod (`.backup`), never prod itself. Run migrations,
break the schema, whatever — reset by tearing down and re-cloning. Prod is never in the
blast radius. Promotion is separate and manual: approve in the preview UI, *then* deploy the
same build to prod.

## Generalizing (the open-source / GUI idea)

Nothing here is LP-specific except the compose files and the hostname. To serve all projects:
- Use a neutral wildcard: `*.preview.<your-domain>` → one tunnel, one Traefik.
- Per-project: a `docker-compose.preview.yml` + a DB-clone step. The `preview` script takes a
  project arg.
- A GUI is a thin layer over Traefik's API (list/route running previews) + the script
  (up/down) + `docker` (status/logs). That's the seam to build on if this becomes a tool.
