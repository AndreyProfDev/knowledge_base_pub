# tools-knowledge-base-qdrant

The Qdrant `VectorStore` adapter for the Knowledge Base, registered as `qdrant`
in the `tools_knowledge_base.vector_stores` entry-point group and picked with
`vector_store.backend: qdrant`.

One collection per embedder (`VectorParams(size=dimensions, distance=COSINE)`),
partitioned by a `kind` keyword payload index with `is_tenant=True` (created on a
server only: local mode has no payload indexes). An existing collection whose
distance is not cosine is refused.
`vector_store.qdrant.location` is `":memory:"` (in-process local mode, the
`testing` overlay) or a server URL.

Writes are conditional on `updated_at`: an upsert onto a point with an equal or
newer `updated_at` leaves it, and `delete(..., older_than=...)` spares newer
points.
