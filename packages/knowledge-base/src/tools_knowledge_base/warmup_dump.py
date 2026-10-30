"""The worker's copy of every stored item in ``warmup.path``, one ``<kind>-<item_id>.yaml`` each."""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import JsonValue

from tools_knowledge_base.errors import WarmupDumpFailed


def dump_file_name(kind: str, item_id: UUID) -> str:
    """The file the dump owns for this item; warm-up lets it win over a hand-written copy."""
    return f"{kind}-{item_id}.yaml"


def write_dump(root: Path, kind: str, item_id: UUID, payload: Mapping[str, JsonValue]) -> None:
    """Atomically replace the item's dump file, creating ``root`` if missing.

    Raises:
        WarmupDumpFailed: the directory or file cannot be written.
    """
    name = dump_file_name(kind, item_id)
    # A dotfile, so a crash leaving it behind is skipped by warm-up. One temp name per item
    # is safe only while huey runs a single worker (``queue.run_consumer`` pins it).
    temp = root / f".{name}.tmp"
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


def _fsync_dir(root: Path) -> None:
    # Else a power loss can undo the rename or unlink: the old or removed file comes back.
    fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
