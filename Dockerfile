# One image for every Python service of the knowledge base: the MCP server, the
# REST API and the write worker. Each package's console scripts land on PATH, so
# compose picks the service with `command:` and nothing else is built.
#
# The COPY order below is load-bearing: manifests first, then dependencies, then
# source. Editing a .py file must not invalidate the dependency layer.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Layer 1 — manifests only. READMEs are included because each pyproject.toml
# declares `readme = "README.md"` and the build backend fails without it.
COPY pyproject.toml uv.lock README.md ./
COPY packages/config/pyproject.toml       packages/config/README.md       packages/config/
COPY packages/knowledge-base/pyproject.toml packages/knowledge-base/README.md packages/knowledge-base/
COPY packages/knowledge-base-api/pyproject.toml packages/knowledge-base-api/README.md packages/knowledge-base-api/
COPY packages/knowledge-base-entity/pyproject.toml packages/knowledge-base-entity/README.md packages/knowledge-base-entity/
COPY packages/knowledge-base-knowledge/pyproject.toml packages/knowledge-base-knowledge/README.md packages/knowledge-base-knowledge/
COPY packages/knowledge-base-lancedb/pyproject.toml packages/knowledge-base-lancedb/README.md packages/knowledge-base-lancedb/
COPY packages/knowledge-base-qdrant/pyproject.toml packages/knowledge-base-qdrant/README.md packages/knowledge-base-qdrant/
COPY packages/knowledge-base-workflow/pyproject.toml packages/knowledge-base-workflow/README.md packages/knowledge-base-workflow/
COPY packages/mcp-server/pyproject.toml   packages/mcp-server/README.md   packages/mcp-server/

# Layer 2 — third-party dependencies only. `--no-install-workspace` skips the
# root project *and* every member, so this layer is invalidated by pyproject or
# uv.lock edits and nothing else. (`--no-install-project` would skip only the
# root and then fail trying to build the members from absent sources.)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

# Layer 3 — the source. Changing it re-runs only this cheap final sync.
COPY packages/ packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim AS runtime

# `prod` because a container gets its secrets injected by the runtime
# (compose `env_file:`, `docker run -e`), never from a .env file on disk.
ENV PATH=/app/.venv/bin:$PATH \
    TOOLS_ENV=prod \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

RUN useradd --create-home --uid 10001 app
# A new named volume copies the image directory and its owner; without this
# /data mounts root-owned and `app` cannot create the knowledge-base queue file.
RUN mkdir /data && chown app /data
USER app

# No ENTRYPOINT: the console scripts are already on PATH, so `docker run <img>`
# serves the MCP endpoint and `docker run <img> knowledge-base-api` the REST API.
CMD ["knowledge-base-mcp"]
