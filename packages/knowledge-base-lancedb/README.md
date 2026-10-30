# tools-knowledge-base-lancedb

The embedded LanceDB `VectorStore` adapter for the Knowledge Base, registered as
`lancedb` in the `tools_knowledge_base.vector_stores` entry-point group and picked
with `vector_store.backend: lancedb` (the `local` overlay).

One table per embedder under `vector_store.lancedb.path`, with columns `id`, `kind`,
`updated_at` (`timestamp[us, tz=UTC]`, read back zone-aware), `payload` (JSON) and `vector`
(fixed-size float32 list). The connection re-reads every commit
(`read_consistency_interval=0`), so the worker, the CLI and stdio servers, each its
own process over one directory, see each other's writes.

Writes are conditional on `updated_at`, as in the Qdrant adapter. Once a table has
more than `max_small_fragments` small fragments, `upsert` compacts it with
`optimize()`.
