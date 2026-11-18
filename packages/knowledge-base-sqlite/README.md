# tools-knowledge-base-sqlite

The SQLite `VectorStore` adapter for the Knowledge Base, registered as `sqlite` in the
`tools_knowledge_base.vector_stores` entry-point group and picked with
`vector_store.backend: sqlite`. Standard library only: `sqlite3`, `array`, `math`.

`vector_store.sqlite.path` is one database file. A `_collections(name, dimensions)` table
records each collection's dimension; each collection is a table of `id` (UUID text,
primary key), `kind` (indexed), `updated_at` (integer microseconds since the UTC epoch),
`payload` (JSON) and `embedding` (float32 BLOB).

`search` is exact: it scores the query against every stored embedding of the requested
kinds by cosine similarity, in pure Python (about 21 ms at 326 points of 1,536
dimensions, linear in the point count). Writes are conditional on `updated_at`, as in the
Qdrant adapter.

Several processes may share the file. Every connection (one per thread) runs in WAL mode
with a 5 s busy wait, and each `upsert` or `delete` is one `BEGIN IMMEDIATE` transaction,
so a writer waits its turn instead of failing. The store takes already-computed vectors:
nothing slow runs inside a transaction.

**The file must be on a local filesystem.** SQLite locking is not reliable over NFS or
SMB.
