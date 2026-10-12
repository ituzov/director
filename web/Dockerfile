FROM node:24-trixie-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

FROM node:24-trixie-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# версия из git-тега: запекается в меню при сборке
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-trixie-slim
WORKDIR /app
# и здесь: динамические страницы читают версию при запросе, а не при сборке
ARG APP_VERSION=dev
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000 APP_VERSION=$APP_VERSION
COPY --from=build --chown=node:node /app/.next/standalone ./
# standalone не копирует статику сам
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
