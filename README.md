# knowledge_base

A personal knowledge base of typed memories: each memory is a kind (`knowledge`,
`entity`, `workflow`), embedded and stored as a point in a pluggable vector store
(Qdrant or LanceDB). It is usable as MCP tools for agents, a CLI, a REST API with
a React UI, and an importable library.

| Package | Import | What it does |
| --- | --- | --- |
| `packages/config` | `knowledge_base_config` | Structured settings: frozen pydantic models from layered YAML |
| `packages/knowledge-base` | `tools_knowledge_base` | Typed memory kinds stored as embedded points in a pluggable vector store; CLI `knowledge-base-cli`, worker `knowledge-base-worker` |
| `packages/knowledge-base-api` | `tools_knowledge_base_api` | FastAPI REST server over the knowledge base (`knowledge-base-api`) |
| `packages/knowledge-base-entity` | `tools_knowledge_base_entity` | The `entity` memory kind |
| `packages/knowledge-base-knowledge` | `tools_knowledge_base_knowledge` | The `knowledge` memory kind |
| `packages/knowledge-base-lancedb` | `tools_knowledge_base_lancedb` | LanceDB vector-store adapter |
| `packages/knowledge-base-qdrant` | `tools_knowledge_base_qdrant` | Qdrant vector-store adapter |
| `packages/knowledge-base-workflow` | `tools_knowledge_base_workflow` | The `workflow` memory kind |
| `packages/knowledge-base-ui` | — (npm) | React SPA over the REST API |
| `packages/mcp-server` | `knowledge_base_mcp_server` | The MCP server (`knowledge-base-mcp`), stdio or HTTP on `127.0.0.1:9799/mcp` |

## Setup

```bash
uv sync
make ui-install           # npm ci for packages/knowledge-base-ui (Node 24)
cp .env.example .env      # then put your OPEN_AI_API_KEY in it
```

## Configuration

Settings live in each package's `configs/base/*.yaml`, overlaid by
`configs/<env>/*.yaml` where `TOOLS_ENV` is `local` (default), `testing`, or
`prod`. Secrets are referenced as `${secret:open_ai_api_key}`, which reads the
upper-cased name from the environment. In `local`, a `.env` at the repository
root is loaded first (`override=False`, so an exported shell variable wins).

## Development

```bash
make            # list every target
make check      # the per-change gate: lock-check, lint, typecheck, coverage, ui-check
make mutation-gate  # both 100% mutation gates (~15 min), once before merge
make kb-check   # alias of check
make test
make fmt
make kb-worker  # the write worker on the host (local queue + LanceDB under data/)
make complexity # just the mccabe limit
make complexity-report  # Markdown: score distribution, most complex functions
```

## Running

Compose project `knowledge_base`, two built images: `knowledge-base:latest`
(mcp-server, knowledge-api, knowledge-worker) and `knowledge_base-knowledge-ui`
(the UI's nginx):

```bash
make up         # detached: mcp-server (127.0.0.1:9799/mcp), knowledge-api (:8000), knowledge-ui (:8081)
make serve      # only the MCP server, in the foreground
make mcp-up     # only the MCP server, detached
make kb-up      # only the REST API and UI, detached
make down       # stop and remove the containers; volumes are kept
make clean CONFIRM=delete-volumes  # also DELETE the volumes and both images
```

`make clean` deletes the project's volumes (`knowledge-data`, `qdrant-storage`,
`tei-models`); the first two hold every stored memory and its write queue, so it refuses (exit 1, before any docker command)
unless `CONFIRM=delete-volumes` is set. It removes the images
`knowledge-base:latest` and `knowledge_base-knowledge-ui`; `make ui-e2e` builds
its own `knowledge-base:e2e` and `kb-e2e-knowledge-ui`, which `make clean` leaves alone.

`KB_MCP_PORT`, `KB_API_PORT` and `KB_UI_PORT` move the host ports.

An MCP client can also register `knowledge_base-dev`: this checkout's source over
stdio, **not** the stored memories (see `packages/mcp-server/README.md` for the
client configuration). It sets no `TOOLS_ENV`, so it runs `local`:
LanceDB under `data/lancedb` and a huey queue in `data/knowledge-queue.db`,
whose writes stay pending until `make kb-worker` runs. Without an
`OPEN_AI_API_KEY` (shell or `.env`; or `KB_EMBEDDER=bge-m3`) it exits at
startup. The real memories are in the container's Qdrant, reached through the
`knowledge_base` server (`http://localhost:9799/mcp`).

Tests never touch the network or the real environment: they select the
`testing` overlay (in-memory Qdrant and huey, an empty API key) and inject fakes.

## CI

GitHub Actions runs on demand: `.github/workflows/ci.yml` keeps every job, but
only `workflow_dispatch` triggers it. The local merge gate is two targets.
`make check` (~30 s) is the per-change gate. `make mutation-gate` (~15 min) is
the 100% mutation gate, `make mutation FRESH=1` (mutmut over every Python
package) then `make ui-mutation FRESH=1` (Stryker over the UI's `src/lib/**`);
it must be green before merge and runs once per change, at the end, not after
every edit. To iterate on one package or file:
`make mutation FRESH=1 PKG=packages/<pkg>`; a mutmut name glob from the package
dir, `uv run --project ../.. mutmut run "<module>.*"`; or, after `make ui-generate`
(`--ignore-scripts` skips it), in `packages/knowledge-base-ui`,
`npm run --ignore-scripts mutate -- --mutate src/lib/<file>.ts --force`
(the script sets the `de_DE` locale the tests require).

Running CI on every push and pull request:

1. In `.github/workflows/ci.yml`, delete `workflow_dispatch:` and the
   `CI-DISABLED` comment, and uncomment `pull_request:`, `push:` and
   `branches: [main]`. `grep -n 'CI-DISABLED' .github/workflows/ci.yml` finds
   the block.
2. Push, and wait for one green run on `main`.
3. Optionally require the checks. This needs repo-admin auth:

```
gh api -X PUT repos/{owner}/{repo}/branches/main/protection \
  -H "Accept: application/vnd.github+json" --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lock-check", "ruff", "typecheck", "complexity", "coverage", "check", "kb-check"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```
