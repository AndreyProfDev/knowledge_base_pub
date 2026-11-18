"""The worker's copy of every stored item in ``warmup.path``, one ``<kind>-<item_id>.yaml`` each."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import JsonValue

from tools_knowledge_base.errors import WarmupDumpFailed, stored_as
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base.store.protocol import Point, VectorStore


def dump_file_name(kind: str, item_id: UUID) -> str:
    """The file the dump owns for this item; warm-up lets it win over a hand-written copy."""
    return f"{kind}-{item_id}.yaml"


def write_dump(root: Path, kind: str, item_id: UUID, payload: Mapping[str, JsonValue]) -> None:
    """Atomically replace the item's dump file, creating ``root`` if missing.

    Raises:
        WarmupDumpFailed: the directory or file cannot be written.
    """
    name = dump_file_name(kind, item_id)
    temp = _temp_path(root, name)
    text = _dump_text(kind, payload)
    try:
        root.mkdir(parents=True, exist_ok=True)
        with temp.open("wb") as file:
            file.write(text.encode())
            file.flush()
            # Else a power loss can leave a zero-length file, which loads as no items.
            os.fsync(file.fileno())
        temp.replace(root / name)
        _fsync_dir(root)
    except OSError as exc:
        msg = f"cannot write dump file {root / name}: {exc}"
        raise WarmupDumpFailed(msg) from exc


def _temp_path(root: Path, name: str) -> Path:
    # A dotfile, so a crash leaving it behind is skipped by warm-up. Unique per process and
    # thread: several conversation processes write the same item's file concurrently.
    return root / f".{name}.{os.getpid()}.{threading.get_ident()}.tmp"


def _dump_text(kind: str, payload: Mapping[str, JsonValue]) -> str:
    document = {kind: [dict(payload)]}
    dump = partial(yaml.safe_dump, sort_keys=False)  # pragma: no mutate, equivalent: None is falsy
    text = dump(document, allow_unicode=True)
    # PyYAML writes a raw U+0085 into a quoted scalar, which loads back as a space;
    # escaped output (``\N``) round-trips.
    if yaml.safe_load(text) != document:
        text = dump(document)
    return text


def dump_holds(root: Path, kind: str, item_id: UUID, payload: Mapping[str, JsonValue]) -> bool:
    """Whether the item's dump file loads as exactly ``payload``; unreadable or invalid does not.

    ``safe_dump`` quotes every string ``safe_load`` would resolve to another type, so a
    re-indented or differently formatted file still holds the same payload.
    """
    try:
        text = (root / dump_file_name(kind, item_id)).read_bytes().decode()
        held: object = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    return held == {kind: [dict(payload)]}


def remove_dump(root: Path, kind: str, item_id: UUID) -> None:
    """Delete the item's dump file; a missing one is not an error.

    Raises:
        WarmupDumpFailed: the file exists and cannot be removed.
    """
    path = root / dump_file_name(kind, item_id)
    try:
        path.unlink()
        _fsync_dir(root)
    except FileNotFoundError:
        return
    except OSError as exc:
        msg = f"cannot remove dump file {path}: {exc}"
        raise WarmupDumpFailed(msg) from exc


def sync_dump(
    store: VectorStore, root: Path, kinds: KindRegistry, kind: str, item_id: UUID
) -> None:
    """Make the dump file mirror the store's copy of ``item_id`` now, or absent with it."""
    # The one dump rule: not the task's payload: an older write the store refused, or an
    # item deleted since, would be restored. Idempotent, so a retry or a forget in any
    # order converges.
    held = [item for item in store.get([item_id]) if item.kind == kind]
    if not held:
        remove_dump(root, kind, item_id)
        return
    model = stored_as(kinds.get(kind).payload_model, held[0].payload, f"{kind} item {item_id}")
    write_dump(root, kind, item_id, model.model_dump(mode="json"))


def upsert_and_sync_dump(
    store: VectorStore,
    root: Path | None,
    kinds: KindRegistry,
    kind: str,
    points: Sequence[Point],
    on_upserted: Callable[[], None] | None = None,
) -> None:
    """Upsert ``points`` of ``kind``, call ``on_upserted`` if given, then sync their dump files.

    ``root`` None leaves the files alone (``warmup.dump`` off).
    """
    # Upsert before dump, so a write that never lands is never dumped.
    store.upsert(points)
    if on_upserted is not None:
        on_upserted()
    if root is not None:
        for point in points:
            sync_dump(store, root, kinds, kind, point.id)


def _fsync_dir(root: Path) -> None:
    # Else a power loss can undo the rename or unlink: the old or removed file comes back.
    fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
