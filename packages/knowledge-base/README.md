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

Writes are queued in memory inside the server process and worked by one background
thread of that process, started on the first write. A write still queued when the
process exits is lost; a new process never picks up another's writes, and
`get_memory_request` answers only for ids its own process issued. A write that
raises is retried twice in process (after 1 s, then 2 s). The CLI drains its own
queue at once and prints the final status. Writes (refused before they are queued)
and `search` need the active embedder's key, so put `OPEN_AI_API_KEY` in `.env`;
`get`, `list` and `delete` run without it, and a delete removes the item and its
dump file inline.

```bash
knowledge-base-cli store-knowledge --category fact --content "the sky is blue"  # embeds, stores, prints done
knowledge-base-cli search "sky colour"                                          # the item, with its score
knowledge-base-cli update-knowledge <id> --category fact --content "the sky is blue by day"
knowledge-base-cli delete knowledge <new-id>                                    # removes item and dump file
```

Verbs: `store-<kind>` and `update-<kind> <id>` for each installed kind, then
`search` (`--kind`, `--top-k`, `--min-score`), `get <kind> <id>`,
`list <kind>` (`--limit`, default 50, and `--cursor`), `delete <kind> <id>`,
`request-status <request-id>`, `kinds` (each kind's character cap and payload JSON
Schema), `warmup` and `reembed --from <collection>`.

Every surface refuses `limit`/`top_k` outside 1..1000 (`search.top_k` too, on
load), a blank query and a non-finite `min_score`.

Changing model / re-embed: each embedder writes its own collection
(`memory-<vector space>`). After switching `KB_EMBEDDER`, run
`knowledge-base-cli reembed --from <old collection>` to copy every item into the
new one; it skips items already there. It exits 1 when some items were too long
for the new embedder, as the copy is then incomplete. Each run journals the ids it
found or copied, per (new collection, old collection), in a sidecar SQLite file
next to the store (`reembed-journal.sqlite3`; LanceDB: inside `lancedb.path`, SQLite:
beside the database file), so a re-run skips an item deleted or reworded since
instead of copying it back; wiping that file loses the journal. Qdrant has no
local directory, so its journal lasts one run.

```python
from knowledge_base_config import environment_from_env
from tools_knowledge_base import operations
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.context import open_knowledge_base

kb = open_knowledge_base(get_settings(environment_from_env()))
accepted = operations.store_memory(
    kb, "knowledge", {"category": "fact", "content": "the sky is blue"}
)
operations.get_memory_request(kb, accepted.request_id).status  # "queued" until the thread runs it
operations.search_memory(kb, "sky colour", top_k=3)
```

Settings (`configs/base/knowledge_base.yaml`): the configured
embedders (`embeddings.active`, `${oc.env:KB_EMBEDDER,openai-large}`), search
defaults, the vector store, `item_limits` (each kind's cap on its whole embed text,
`default_max_chars` 500 for a kind missing from `max_chars`) and `warmup.path`
(`$KB_DATA_DIR/warmup`). `local` runs SQLite in `$KB_DATA_DIR`
(`KB_VECTOR_STORE` picks another); `testing` runs Qdrant in memory.

## Warm-up

`warmup` (`warmup_memory`) loads every item in `warmup.path` and writes only those
missing or changed, itself and before it returns: it embeds them 32 per call, upserts
each batch and, with `warmup.dump`, writes their dump files. It never deletes, but
overwrites a stored item with the same key. Run it by hand with `make kb-warmup`
(`TOOLS_ENV` picks the store; it needs the embedder key); nothing runs it at server
start and it is not an MCP tool. Any bad entry rejects the run with every error, and
nothing is written. A batch that fails to embed or write stops the run with
`WarmupPartiallyWritten`, naming the kind, the batch and how many items were written;
those stay written, and a rerun skips them as unchanged. An error is at `(file,)` for a bad file or directory entry, `(file, kind)`
for an unknown kind or a non-list, and `(file, kind, index, ...)` otherwise. A
missing or unlistable directory, or one holding no items, is an error too.

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

With `warmup.dump` (on in `base`, off in `testing`) every write, and warm-up itself,
write every item they store to `<kind>-<item_id>.yaml` in `warmup.path`, so a wiped store re-warms from
the directory.

- Updating an item to a new key removes the old file in the same request, unless
  the old item is newer than the update (both are then kept).
- A delete first drains the queue, then removes the item from the store and the
  file inline, and returns a request already `done`. If the file removal fails after
  the store delete, the request is `failed` with the error: the item is gone but the
  file is still there, so delete it by hand.
- The server's own `warmup.dump` decides whether the file is touched. With it off,
  a store, update or delete whose item already has a dump file fails without retry,
  since warm-up would restore that stale copy, unless the write is of exactly the
  payload that file holds (a rebuild from the dump).
- A later edit to a hand-written copy of a dumped item is shadowed by the dump
  file: edit the dump file.
- The dump removes only its own files: a deleted or renamed item with a
  hand-written copy comes back at the next warm-up until that copy is removed.

## MCP

The `server` extra provides `register`, which `knowledge-base-mcp`
(`packages/mcp-server`) calls to serve, for each installed kind `store_<kind>`,
`update_<kind>`, `get_<kind>`, `list_<kind>` and `delete_<kind>`, plus
`search_memory` and `get_memory_request`. With the active embedder's key empty, registration is
declined and the server exits non-zero, naming the key on stderr. Over stdio
(`TOOLS_ENV=local MCP_TRANSPORT=stdio uv run knowledge-base-mcp`) the server
works its own writes; when stdin closes it logs how many were still queued and exits
without waiting for them.

For a local embedder, run your own TEI serving bge-m3 at `http://localhost:8080/v1`
(the `bge-m3` embedder's `base_url`), then re-embed the old collection into the
new one:

```
KB_EMBEDDER=bge-m3 uv run knowledge-base-cli reembed --from memory-text-embedding-3-large-3072
```
