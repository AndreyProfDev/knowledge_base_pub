# tools-knowledge-base-api

A FastAPI REST server over the knowledge base's operations: one route set over
`/memory/{kind}` for every installed kind, plus `/search`, `/requests/{request_id}`
and `/kinds`. `knowledge-base-api` serves it on `host:port`: `0.0.0.0:8000` in base
(for the container), `127.0.0.1:8000` under `TOOLS_ENV=local`. It refuses to start
with a keyless embedder or no kinds installed. `/docs` is the OpenAPI UI.
In compose, `make kb-up` starts it with `qdrant` and `knowledge-worker` on
`127.0.0.1:8000`. A bare `docker compose up -d --wait knowledge-api` skips
`make kb-warmup-dir`, so every dump, and with it every write, fails after retries.

Writes, `DELETE` included, answer `202` with `Location: /requests/{request_id}`;
the worker runs them. `DELETE` removes the item at once and queues its dump file's
removal; failing to queue that answers `500` with `detail` (`DumpRemovalNotQueued`).
`UnknownKind`, `ItemNotFound` and `UnknownRequest` answer `404`; a payload the kind
refuses answers `422` in FastAPI's own validation-error body, without `input`;
a stored item that fails its model (`StoredItemInvalid`) answers `500`.

`POST /warmup` loads the configured warm-up directory (no path parameter) and
answers `200` with the run's report; any bad file or item is a `422` with each
`loc` at `(file, kind, index, ...)` and nothing queued; a missing, unreadable or
itemless directory is a `404` naming it; a run stopped partway by storage is a `503`.
`GET /warmup/{run_id}` answers its progress, or `404` for an unknown run.

No auth: `TrustedHostMiddleware` (`allowed_hosts`) answers `400` to any other `Host`,
so a DNS-rebound page cannot reach it.

`openapi.json` is the committed `app.openapi()`, which the web UI's client is
generated from; `tests/test_openapi_snapshot.py` fails when it drifts, and its
message gives the command that regenerates it.
