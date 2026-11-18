# knowledge_base

A personal knowledge base of typed memories: each memory is a kind (`knowledge`,
`entity`, `workflow`), embedded and stored as a point in a pluggable vector store
(Qdrant, LanceDB or SQLite). It is usable as MCP tools for agents, a CLI, and an
importable library.

| Package | Import | What it does |
| --- | --- | --- |
| `packages/config` | `knowledge_base_config` | Structured settings: frozen pydantic models from layered YAML |
| `packages/knowledge-base` | `tools_knowledge_base` | Typed memory kinds stored as embedded points in a pluggable vector store; CLI `knowledge-base-cli` |
| `packages/knowledge-base-entity` | `tools_knowledge_base_entity` | The `entity` memory kind |
| `packages/knowledge-base-knowledge` | `tools_knowledge_base_knowledge` | The `knowledge` memory kind |
| `packages/knowledge-base-lancedb` | `tools_knowledge_base_lancedb` | LanceDB vector-store adapter |
| `packages/knowledge-base-qdrant` | `tools_knowledge_base_qdrant` | Qdrant vector-store adapter |
| `packages/knowledge-base-sqlite` | `tools_knowledge_base_sqlite` | SQLite vector-store adapter |
| `packages/knowledge-base-workflow` | `tools_knowledge_base_workflow` | The `workflow` memory kind |
| `packages/mcp-server` | `knowledge_base_mcp_server` | The MCP server (`knowledge-base-mcp`), stdio (default) or HTTP via `MCP_TRANSPORT=http` on `127.0.0.1:9799/mcp` |

## Setup

```bash
uv sync
mkdir -p "${KB_DATA_DIR:-$HOME/.local/share/knowledge-base}"
cp .env.example "${KB_DATA_DIR:-$HOME/.local/share/knowledge-base}/.env"  # put your OPEN_AI_API_KEY in it
```

## Configuration

Settings live in each package's `configs/base/*.yaml`, overlaid by
`configs/<env>/*.yaml` where `TOOLS_ENV` is `local` (default) or `testing`.
Secrets are referenced as `${secret:open_ai_api_key}`, which reads the
upper-cased name from the environment. In `local`, `${KB_DATA_DIR}/.env` is
loaded first (`override=False`, so an exported shell variable wins); for a
checkout, put the key there or export it.

## Development

```bash
make            # list every target
make check      # the per-change gate: lock-check, lint, typecheck, coverage
make mutation-gate  # the 100% mutation gate (~15 min), once before merge
make kb-check   # alias of check
make test
make fmt
make complexity # just the mccabe limit
make complexity-report  # Markdown: score distribution, most complex functions
```

## Running

### From a wheel directory (no clone)

The server ships as a directory of wheels that runs over stdio through `uvx`.
The target needs `uv` and network access to PyPI (for the third-party wheels);
no clone, no Docker. Stdio is the default transport; `MCP_TRANSPORT=http` serves
HTTP on `127.0.0.1:9799/mcp` instead.

Build on the dev machine (the version is derived from git, so each build at a
new commit gets a new one, e.g. `0.1.1.dev12+g<sha>`, plus `.dYYYYMMDD` on a
dirty tree):

```bash
make dist        # dist/knowledge-base-mcp/ and dist/knowledge-base-mcp.tar.gz
make dist-smoke  # optional: runs the dir through uvx outside the repo (needs PyPI)
```

`dist/knowledge-base-mcp/` holds the 9 wheels, `constraints.txt` (the locked
third-party pins) and a uv-written `.gitignore`. Copy the dir or the tarball to
the target and untar it to a fixed dir, e.g. `~/.local/share/knowledge-base-mcp-dist`.
That path ends up in the registration, so keep it there.

```bash
mkdir -p ~/.local/share/knowledge-base-mcp-dist
tar -xzf knowledge-base-mcp.tar.gz -C ~/.local/share/knowledge-base-mcp-dist
```

Register it in your MCP client (with `<dir>` the absolute path above), e.g. with
Claude Code:

```bash
claude mcp add --scope user knowledge_base -- uvx --python 3.12 -c <dir>/constraints.txt --find-links <dir> --from knowledge-base-mcp-server knowledge-base-mcp
```

For another store use `--from 'knowledge-base-mcp-server[qdrant]'` (or
`[lancedb]`) and set `KB_VECTOR_STORE=qdrant`. Keep `--python 3.12` (without it
uvx picks the newest Python) and `-c constraints.txt` (without it uvx ignores
`uv.lock` and resolves fresh third-party versions).

- **Configure.** `cp .env.example <data dir>/.env` and set `OPEN_AI_API_KEY`, or
  set `KB_EMBEDDER=bge-m3` and run TEI per `packages/knowledge-base/README.md`.
  The default embedder is OpenAI `text-embedding-3-large` (`openai-large`, 3072
  dimensions); `KB_EMBEDDER=openai-small` picks `text-embedding-3-small`.
  Without a key the server refuses to start and names that path.
- **Data.** `KB_DATA_DIR`, else `$XDG_DATA_HOME/knowledge-base`, else
  `~/.local/share/knowledge-base`. Data never lives in the dist dir or in uv's
  cache (where the uvx environment lives), so replacing the dist or clearing the
  cache keeps every memory.
- **Upgrade.** Run `make dist` at a newer commit and replace the dir contents,
  deleting the old wheels (two versions side by side resolve to the newer, but
  stale files accumulate). The next client launch picks it up. A rebuild with the
  same version is invisible to a warm uvx cache (even with `--refresh` or
  `--reinstall-package`), which is why every build gets its own version. For a
  URL `--find-links`, run `uvx --refresh ...` once so uv revalidates its HTTP
  cache.
- **GitHub release hosting.** `--find-links` needs an HTML page or a dir of
  links (unverified for GitHub:
  `https://github.com/<owner>/<repo>/releases/expanded_assets/<tag>`). For a
  private repo anonymous downloads return 404: download the assets with an
  authenticated token to a local dir and point `--find-links` there.

### Moving an existing knowledge base to a new machine

Copy `<old data dir>/warmup/` to the new data dir. It holds one YAML per item as
`<kind>-<id>.yaml`, kept in sync by every store, update and delete. You can also
copy `knowledge.sqlite3`: that works when the embedder is the same and saves
re-embedding. Then load the dump, without `make` or a clone:

```bash
OPEN_AI_API_KEY=... uvx --python 3.12 -c <dir>/constraints.txt --find-links <dir> --with knowledge-base-mcp-server --from tools-knowledge-base knowledge-base-cli warmup
```

It re-embeds and writes every item not already stored unchanged, so it needs the
embedder key (or `KB_EMBEDDER=bge-m3`). An item of a kind that is not installed
fails the run before any embedding, with `unknown memory kind '<kind>'; installed:
[...]`. From a clone the same step is `make kb-warmup`.

### Stdio server on the host

`make install-mcp` installs `knowledge-base-mcp` into its own venv outside the
checkout (`INSTALL_VENV`, default `~/.local/share/knowledge-base-mcp`;
non-editable, bytecode compiled) and prints the registration line, which it does
not run:

```bash
make install-mcp                  # SQLite store only
make install-mcp EXTRAS=qdrant    # or EXTRAS=lancedb: adds that store
claude mcp add --scope user knowledge_base --env MCP_TRANSPORT=stdio -- ~/.local/share/knowledge-base-mcp/bin/knowledge-base-mcp
```

Stdio is the default transport, so `--env MCP_TRANSPORT=stdio` is optional (it
still wins over a shell that exports `MCP_TRANSPORT=http`). The server checks
the embedder key at start and refuses to start without one. It opens nothing
else at start: the store, the embedder and the write queue open on the first
tool call that needs them, so an unreachable store or a dimension mismatch
fails that call, not the start. Writes are queued in the server process; poll
`get_memory_request` until `done`.

- Data lives in `KB_DATA_DIR` (default `$XDG_DATA_HOME/knowledge-base`, else
  `~/.local/share/knowledge-base`): `knowledge.sqlite3` and the `warmup/` dump.
- The embedder key `OPEN_AI_API_KEY` comes from the process environment (e.g.
  the client config's `--env OPEN_AI_API_KEY=...`) or from `${KB_DATA_DIR}/.env`.
  A real environment variable wins over the file. With neither, the server
  refuses to start and names `<data dir>/.env`. `KB_EMBEDDER=bge-m3` needs no key.
- `KB_VECTOR_STORE` switches the store (`qdrant` or `lancedb`, default `sqlite`)
  and needs the matching extra installed. Without it the first store call fails
  with `vector store '<name>' is not installed; install
  knowledge-base-mcp-server[<name>]`, while `tools/list` still works.

An MCP client can also register `knowledge_base-dev`: this checkout's source over
stdio, **not** the stored memories (see `packages/mcp-server/README.md` for the
client configuration). It sets no `TOOLS_ENV`, so it runs `local`:
SQLite under `data/dev`, and writes are queued in memory and worked by a
thread of that process. Without an
`OPEN_AI_API_KEY` it refuses to start: put the key in `data/dev/.env` (or export
it), or set `KB_EMBEDDER=bge-m3`. The real memories are the `knowledge_base` stdio
server's, in `$KB_DATA_DIR/knowledge.sqlite3`. The live dump is `$KB_DATA_DIR/warmup`; the repo's
`knowledge-warmup/` is no longer written.

Tests never touch the network or the real environment: they select the
`testing` overlay (in-memory Qdrant, an empty API key) and inject fakes.

## CI

GitHub Actions runs on demand: `.github/workflows/ci.yml` keeps every job, but
only `workflow_dispatch` triggers it. The local merge gate is two targets.
`make check` (~30 s) is the per-change gate. `make mutation-gate` (~15 min) is
the 100% mutation gate, `make mutation FRESH=1` (mutmut over every Python
package); it must be green before merge and runs once per change, at the end,
not after every edit. To iterate on one package or file:
`make mutation FRESH=1 PKG=packages/<pkg>`; or a mutmut name glob from the package
dir, `uv run --project ../.. mutmut run "<module>.*"`.

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
