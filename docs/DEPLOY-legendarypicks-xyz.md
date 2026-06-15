# Deploying legendarypicks.xyz (Dockerized)

Stack: **Next.js Flow dapp** (frontend, port 3000, yarn) + **FastAPI sports backend**
(`backend/sports_service.py`, uvicorn, port 8000). This guide containerizes both, runs them with
docker-compose, and serves them at `legendarypicks.xyz` behind nginx + HTTPS.

> Flow note: a live site must target **testnet or mainnet**, not the local emulator. Set
> `NEXT_PUBLIC_FLOW_NETWORK=mainnet` (or `testnet`) and make sure the Cadence contracts in
> `flow.json` are deployed to that network. The `dev:*` scripts that spin up `flow emulator` /
> `dev-wallet` are for local only — do NOT run them in prod.

---
## 1. Backend image — `backend/Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD ["uvicorn", "sports_service:app", "--host", "0.0.0.0", "--port", "8000"]
```
`backend/.dockerignore`: `venv`, `__pycache__`, `data/cache` (keep static data if the app needs it).

## 2. Frontend image — `Dockerfile` (repo root)
Next env vars prefixed `NEXT_PUBLIC_` are baked at BUILD time, so the Flow network + API base must be
build args. First add `output: 'standalone'` to `next.config.js` for a small runtime image.
```dockerfile
# ---- build ----
FROM node:20-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json yarn.lock* .yarnrc.yml ./
COPY .yarn ./.yarn
RUN yarn install --immutable
COPY . .
ARG NEXT_PUBLIC_FLOW_NETWORK=mainnet
ARG NEXT_PUBLIC_API_BASE=/api
ENV NEXT_PUBLIC_FLOW_NETWORK=$NEXT_PUBLIC_FLOW_NETWORK
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN yarn build
# ---- run ----
FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```
> If `output:'standalone'` isn't enabled, fall back to copying the whole build and `CMD ["yarn","start"]`.
> Confirm how the frontend calls the backend (search for the API base/fetch URL) and wire it to
> `NEXT_PUBLIC_API_BASE=/api` so nginx routes it to the backend.

## 3. `docker-compose.yml` (repo root)
```yaml
services:
  backend:
    build: ./backend
    environment: { PORT: "8000" }
    expose: ["8000"]
    restart: unless-stopped
  frontend:
    build:
      context: .
      args:
        NEXT_PUBLIC_FLOW_NETWORK: mainnet
        NEXT_PUBLIC_API_BASE: /api
    depends_on: [backend]
    expose: ["3000"]
    restart: unless-stopped
```
Build + run: `docker compose up -d --build`. (Both are `expose` not `ports` — nginx on the host
reaches them; or add `ports: ["127.0.0.1:3000:3000"]` etc. if nginx runs on the host not in compose.)

## 4. nginx vhost — `/etc/nginx/sites-available/legendarypicks.xyz`
(see `server-notes/nginx-enable-new-site.md` for the full runbook)
```nginx
server {
    listen 80;
    server_name legendarypicks.xyz www.legendarypicks.xyz;
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;   # strips /api/ -> backend root
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```
```bash
ln -s /etc/nginx/sites-available/legendarypicks.xyz /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d legendarypicks.xyz -d www.legendarypicks.xyz --redirect -m you@email --agree-tos -n
```
(If compose uses `expose` only, run nginx in the same compose network instead of on host, and
`proxy_pass http://frontend:3000` / `http://backend:8000`.)

## 5. DNS + checklist
- A record `legendarypicks.xyz` → server IP; `www` A/CNAME.
- `ufw allow 'Nginx Full'`; ports 80/443 open.
- `docker compose ps` both healthy; `curl -I https://legendarypicks.xyz` → 200.
- Backend smoke test: `curl https://legendarypicks.xyz/api/<an endpoint from sports_service.py>`.
- CI/redeploy: `git pull && docker compose up -d --build`.

## 6. Secrets — DO NOT bake into images
`emulator-account.pkey` / `emulator.key` are LOCAL emulator keys — never ship them. Real keys/secrets
go in env (compose `env_file:` or host env), never in the image or git.
