FROM node:20-slim AS codex-cli
ARG CODEX_CLI_VERSION=0.144.1
RUN npm install --global "@openai/codex@${CODEX_CLI_VERSION}" \
    && codex --version

FROM node:20-slim AS frontend-build
WORKDIR /app/apps/frontend
COPY apps/frontend/package.json ./package.json
COPY apps/frontend/package-lock.json ./package-lock.json
COPY apps/frontend/tsconfig.json ./tsconfig.json
COPY apps/frontend/tsconfig.node.json ./tsconfig.node.json
COPY apps/frontend/vite.config.ts ./vite.config.ts
COPY apps/frontend/index.html ./index.html
COPY apps/frontend/public ./public
COPY apps/frontend/src ./src
RUN npm ci && npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HARNESS_DATA_DIR=/data
ENV FRONTEND_DIST_DIR=/app/frontend_dist
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY apps/backend /app/apps/backend
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY schemas /app/schemas
COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/lib/node_modules/@openai/codex /usr/local/lib/node_modules/@openai/codex
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && codex --version
COPY --from=frontend-build /app/apps/frontend/dist /app/frontend_dist
RUN chmod -R a+rX /app/apps/backend
RUN --mount=type=cache,target=/root/.cache/pip pip install .
COPY benchmarks /app/benchmarks
RUN mkdir -p /data
EXPOSE 8080
CMD ["uvicorn", "tabular_harness.main:app", "--host", "0.0.0.0", "--port", "8080"]
