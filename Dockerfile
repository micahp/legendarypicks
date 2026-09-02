# ---- build ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_BASE=/api
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ARG NEXT_PUBLIC_SPORTS_API_URL=/api
ENV NEXT_PUBLIC_SPORTS_API_URL=$NEXT_PUBLIC_SPORTS_API_URL
# GA4 measurement id. Inlined at build time -- a runtime-only env var records nothing.
ARG NEXT_PUBLIC_GA_TRACKING_ID=
ENV NEXT_PUBLIC_GA_TRACKING_ID=$NEXT_PUBLIC_GA_TRACKING_ID
# The API proxy target must be a BUILD arg, not only a runtime env. `output:
# 'standalone'` resolves next.config.js `rewrites()` at BUILD time and bakes the
# destination into the server bundle, so a runtime-only value is read too late
# and the default `http://localhost:8000` ships -- which inside the frontend
# container is the container itself. 2026-08-25: a rebuild produced exactly that
# and every /api/* proxy call returned 500 ECONNREFUSED, so the props board
# rendered "The game slate could not be loaded" for every league while the
# backend answered 200 on the same path. compose sets it in `environment` too;
# that line is correct for SSR but cannot fix a baked rewrite.
ARG API_PROXY_TARGET=http://backend:8000
ENV API_PROXY_TARGET=$API_PROXY_TARGET
RUN npm run build

# ---- run ----
FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
