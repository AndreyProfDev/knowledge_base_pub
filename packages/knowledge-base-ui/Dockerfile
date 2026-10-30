# Built from the repo root (compose `context: .`): `generate` reads
# ../knowledge-base-api/openapi.json.

FROM node:24-alpine AS build

WORKDIR /app/packages/knowledge-base-ui

COPY packages/knowledge-base-ui/package.json packages/knowledge-base-ui/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY packages/knowledge-base-api/openapi.json ../knowledge-base-api/
COPY packages/knowledge-base-ui/index.html packages/knowledge-base-ui/vite.config.ts packages/knowledge-base-ui/tsconfig.json ./
COPY packages/knowledge-base-ui/src/ src/

# Empty runs the grid as an unlicensed trial.
ARG VITE_AG_GRID_LICENSE_KEY=
RUN npm run build


FROM nginx:1.30-alpine

COPY packages/knowledge-base-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/packages/knowledge-base-ui/dist/ /usr/share/nginx/html/
