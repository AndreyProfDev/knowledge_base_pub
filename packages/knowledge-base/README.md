# tools-knowledge-base

The Knowledge Base core: typed memory kinds stored as embedded points in a
pluggable vector store, written through an async queue and read synchronously.

Two plugin seams, both discovered through stevedore entry points:

- `tools_knowledge_base.memory_kinds`: one package per memory kind
  (`knowledge-base-knowledge`, ...), each a `MemoryKind`.
- `tools_knowledge_base.vector_stores`: one package per backend
  (`knowledge-base-lancedb`, `knowledge-base-qdrant`), each a `VectorStore`,
  picked by `vector_store.backend`.

Core imports no kind and no backend: adding the package as a dependency is the
whole activation step.

Writes are queued; `knowledge-base-worker` embeds and stores them (`make kb-worker`
runs it as a consumer under `TOOLS_ENV=local`; `--once` drains the queue and exits).
Writes (refused before they are queued), the worker and `search` need the active
embedder's key, so put `OPEN_AI_API_KEY` in `.env`; `get`, `list` and `delete` run
without it, but a delete queues its dump file's removal for the worker.

```bash
knowledge-base-cli store-knowledge --category fact --content "the sky is blue"  # request + item id
knowledge-base-worker --once                                                    # embeds and stores it
knowledge-base-cli search "sky colour"                                          # the item, with its score
knowledge-base-cli update-knowledge <id> --category fact --content "the sky is blue by day"
knowledge-base-worker --once                                                    # new id stored, old id gone
knowledge-base-cli delete knowledge <new-id>                                    # request + item id
knowledge-base-worker --once                                                    # removes its dump file
```

Verbs: `store-<kind>` and `update-<kind> <id>` for each installed kind, then
`search` (`--kind`, `--top-k`, `--min-score`), `get <kind> <id>`,
`list <kind>` (`--limit`, default 50, and `--cursor`), `delete <kind> <id>`,
`request-status <request-id>`, `kinds` (each kind's character cap and payload JSON
Schema), `warmup`, `warmup-progress <run-id>` and `reembed --from <collection>`.

Every surface refuses `limit`/`top_k` outside 1..1000 (`search.top_k` too, on
load), a blank query and a non-finite `min_score`.

Changing model / re-embed: each embedder writes its own collection
(`memory-<vector space>`). After switching `KB_EMBEDDER`, stop the worker and run
`knowledge-base-cli reembed --from <old collection>` to copy every item into the
new one; it skips items already there. It exits 1 when some items were too long
for the new embedder, as the copy is then incomplete. Each run journals the ids it
found or copied in the new collection (`reembed:<collection>:<id>`) in the queue
database (`queue.path`, `./data/knowledge-queue.db`), so a re-run skips an item
deleted or reworded since instead of copying it back; wiping that database loses
the journal. Keep the worker stopped until the last run: an item the worker writes
and that is deleted between two runs can otherwise come back from the old collection.

```python
from tools_knowledge_base import api as kb

accepted = kb.store("knowledge", {"category": "fact", "content": "the sky is blue"})
kb.request(accepted.request_id).status  # "queued" until the worker runs it
kb.search("sky colour", top_k=3)
```

Settings (`configs/base/knowledge_base.yaml`): the queue, the configured
embedders (`embeddings.active`, `${oc.env:KB_EMBEDDER,openai-small}`), search
defaults, the vector store, `item_limits` (each kind's cap on its whole embed text,
`default_max_chars` 500 for a kind missing from `max_chars`) and `warmup.path`
(`./knowledge-warmup`; `/warmup` in `prod`). `local` runs LanceDB under
`./data/lancedb`; `testing` runs Qdrant in memory; `prod` reads the `qdrant`
compose service.

## Warm-up

`warmup` (`warmup_memory`, `POST /warmup`) loads every item in `warmup.path` and
queues only those missing or changed; it never deletes, but overwrites a stored item
with the same key. Any bad entry rejects the run with every error, and nothing is
queued. An error is at `(file,)` for a bad file or directory entry, `(file, kind)`
for an unknown kind or a non-list, and `(file, kind, index, ...)` otherwise. A
missing or unlistable directory, or one holding no items, is an error too (404).

```yaml
knowledge:             # kind -> list of store_<kind> payloads
  - category: preference
    content: Prefers uv over pip.
```

- Files are `*.yaml`/`*.yml`, read in sorted order; dotfiles are skipped, any other
  entry (a subdirectory too) is an error.
- One document per file; keys are unique strings; values are strings, lists, maps
  or null. Plain scalars stay the string written (`yes`, `42`, `2024-01-02`); any
  other tag (`!!binary`, `!!int`, ...) and an unknown payload field are errors.
- The same key twice across files is an error naming both places, except that a
  dump file's copy wins. A losing copy whose payload differs is listed in the
  report's `shadowed` (hand-written location, dump location); an identical one is not.

### Dump

With `warmup.dump` (on in `base`, off in `testing`) the worker writes every item it
stores to `<kind>-<item_id>.yaml` in `warmup.path`, so a wiped store re-warms from
the directory.

- Updating an item to a new key removes the old file in the same request, unless
  the old item is newer than the update (both are then kept).
- A delete removes the item from the store at once and returns a request that
  removes the file; until that reads `done` the file can bring the item back at the
  next warm-up, and `failed` means the file is still there. If the delete fails with
  `DumpRemovalNotQueued` (REST: 500), the item is gone but no removal was queued:
  delete the file by hand.
- The worker's own `warmup.dump` decides whether the file is touched. With it off,
  a store, update or delete whose item already has a dump file fails without retry,
  since warm-up would restore that stale copy, unless the write is of exactly the
  payload that file holds (a rebuild from the dump).
- A later edit to a hand-written copy of a dumped item is shadowed by the dump
  file: edit the dump file.
- The dump removes only its own files: a deleted or renamed item with a
  hand-written copy comes back at the next warm-up until that copy is removed.

Compose mounts `${KB_WARMUP_DIR:-./knowledge-warmup}` read-only at `/warmup` in
`mcp-server` and `knowledge-api`, and writable in `knowledge-worker`, which runs as
uid 10001: `make kb-warmup-dir` (a prerequisite of `up`, `serve`, `mcp-up` and `kb-up`;
`scripts/kb-warmup-dir.sh`) creates the dir and probes a write from the container.
Only if that fails, on Linux Docker, it grants uid 10001 `rwX` by ACL (`setfacl`;
needs an ACL-capable filesystem and a dir you own) and probes again;
`chown 10001` or `chmod 1777` on the dir work instead. Rootless or userns-remapped
Docker and SELinux fail the probe. `warmup-progress`
counts a request between retries as pending: a failing item reaches `failed` only
after ~150 s.

## MCP and compose

The `server` extra provides `register`, which `knowledge-base-mcp`
(`packages/mcp-server`) calls to serve, for each installed kind `store_<kind>`,
`update_<kind>`, `get_<kind>`, `list_<kind>` and `delete_<kind>`, plus
`search_memory`, `get_memory_request`, `warmup_memory` and
`get_warmup_progress`. With the active embedder's key empty, registration is
declined and the server exits non-zero, naming the key on stderr. Over stdio
(`TOOLS_ENV=local MCP_TRANSPORT=stdio uv run knowledge-base-mcp`) run
`make kb-worker` alongside.

`make serve` (`TOOLS_ENV=prod`) brings up `mcp-server`, `qdrant` and
`knowledge-worker`. `mcp-server` and `knowledge-worker` share the queue file on the
`knowledge-data` volume at `/data`; `qdrant` keeps its points on `qdrant-storage`.

For a local GPU embedder (TEI serving bge-m3 as compose service `embeddings` in
profile `gpu`; NVIDIA GPU and the NVIDIA Container Toolkit required), start it,
serve with it, then re-embed the old collection into the new one:

```
docker compose --profile gpu up -d embeddings
KB_EMBEDDER=bge-m3 make serve
docker compose run --rm -e KB_EMBEDDER=bge-m3 knowledge-worker \
  knowledge-base-cli reembed --from memory-text-embedding-3-small-1536
```
