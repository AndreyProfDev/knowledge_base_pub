# knowledge-base-mcp-server

Serves the knowledge base's tools from **one** MCP endpoint:

```
http://localhost:9799/mcp
```

For each installed kind (`entity`, `knowledge`, `workflow`): `store_<kind>`,
`update_<kind>`, `get_<kind>`, `list_<kind>` and `delete_<kind>`; plus
`search_memory`, `get_memory_request`, `warmup_memory` and
`get_warmup_progress`.

The port is published on loopback only — there is no auth. From another
machine, tunnel: `ssh -L 9799:localhost:9799 <user>@<host>`.

## How the knowledge base gets here

By name, not by discovery: `app.py` builds
`MCPServer("knowledge_base", instructions=SUMMARY)` and calls
`tools_knowledge_base.registration.register(server)`. The `SUMMARY` is what a
client gets at `initialize`.

## Failure behaviour

This server serves nothing else, so a `register` that raises — the active
embedder's key is empty, no kind is installed, a tool name is refused, the store
is unreachable — **ends the process** with exit code 1 and
`knowledge base did not register: <reason>` on stderr. Starting anyway would
look healthy and answer with no tools.

## Two transports

| | `http` (default) | `stdio` |
| --- | --- | --- |
| Who starts it | you, `make serve` | the client spawns it |
| Shared between clients | yes, one container | no, one process each |
| Needs a port / daemon | yes | no |

```bash
uv run knowledge-base-mcp                      # http, on the host
MCP_TRANSPORT=stdio uv run knowledge-base-mcp  # stdio, for a client to spawn
```

`MCP_TRANSPORT` overrides the `transport` setting, because a client config can
set env vars but not edit YAML. Writes are queued, so over stdio run
`make kb-worker` alongside.

## Stable vs dev

Two registrations in an MCP client, and they do not share data. A client that
takes the common `mcpServers` JSON format registers them as:

```json
{
  "mcpServers": {
    "knowledge_base": { "type": "http", "url": "http://localhost:9799/mcp" },
    "knowledge_base-dev": {
      "command": "uv",
      "args": ["run", "knowledge-base-mcp"],
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

| | `knowledge_base` | `knowledge_base-dev` |
| --- | --- | --- |
| Registered in | the client's user-level config — every project | the client's project-level config — this repo only |
| Runs | the built container (`make up`) | source in the checkout (`uv run`) |
| Transport | http, `http://localhost:9799/mcp` | stdio |
| `TOOLS_ENV` | `prod` (compose pins it) | unset, so `local` |
| Store | Qdrant, volume `qdrant-storage` — the real memories | LanceDB under `data/lancedb` |
| Writes | drained by the `knowledge-worker` container | pending in `data/knowledge-queue.db` until `make kb-worker` runs |
| Affected by local edits | no, until `make build` then `make up` | immediately |

Without an embedder key (`OPEN_AI_API_KEY` in the shell or `.env`, or
`KB_EMBEDDER=bge-m3`), `knowledge_base-dev` exits at startup with the reason on
stderr. Stored memories are only ever reachable through `knowledge_base`.

stdio must be spawned **inside the workspace** — `uv run` needs to find the
root `pyproject.toml`. The startup log on stderr reports how many tools
registered.

Settings live in `configs/base/mcp_server.yaml`: `host`, `port`, `path`, and
`allowed_hosts` — the last matters because the SDK's DNS-rebinding protection
rejects unexpected `Host` headers with `421 Misdirected Request`; it admits
`localhost`/`127.0.0.1` on any port, so a moved `KB_MCP_PORT` still answers.
The base binds `0.0.0.0` for the container; `configs/local/` (the host,
`TOOLS_ENV` unset) binds `127.0.0.1`.
