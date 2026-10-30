"""Warm-up files: parsed and validated whole, every failure collected before any is raised."""

from __future__ import annotations

import re
from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import Any, NamedTuple, override
from uuid import UUID

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError
from yaml.constructor import ConstructorError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import UnknownKind, WarmupDirectoryEmpty, WarmupDirectoryMissing
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.models import WarmupShadow
from tools_knowledge_base.operations.store import item_id_of, validate_payload
from tools_knowledge_base.warmup_dump import dump_file_name

type Loc = tuple[str | int, ...]

_SUFFIXES = frozenset({".yaml", ".yml"})
_STR, _SEQ, _MAP, _NULL = (f"tag:yaml.org,2002:{t}" for t in ("str", "seq", "map", "null"))


class _WarmupLoader(yaml.SafeLoader):
    """Mappings with unique string keys, lists, strings and null; nothing else loads.

    A plain scalar is the string as written (``yes``, ``2024-01-02``, ``42``), except null.
    Any explicit tag but these four is refused; ``<<`` is a plain key, never a merge.
    """

    @override
    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> dict[Hashable, Any]:
        if not isinstance(node, yaml.MappingNode):
            # ``!!map`` on a sequence or scalar: its ``value`` is not key/value pairs.
            problem = f"only a mapping can be tagged {node.tag}"
            raise ConstructorError(None, None, problem, node.start_mark)
        seen: set[str] = set()
        for key_node, _ in node.value:
            key: object = self.construct_object(key_node, deep=deep)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if not isinstance(key, str):
                problem = f"a {key_node.tag} key; keys must be strings"
            elif key in seen:
                problem = f"key {key!r} is repeated"
            else:
                seen.add(key)
                continue
            raise ConstructorError(None, None, problem, key_node.start_mark)
        return super().construct_mapping(node, deep)


def _refuse(_loader: _WarmupLoader, node: yaml.Node) -> None:
    raise ConstructorError(None, None, f"tag {node.tag} is not supported", node.start_mark)


_WarmupLoader.yaml_implicit_resolvers = {}
_WarmupLoader.yaml_constructors = {
    tag: yaml.SafeLoader.yaml_constructors[tag] for tag in (_STR, _SEQ, _MAP, _NULL)
}
_WarmupLoader.add_constructor(None, _refuse)  # pyright: ignore[reportArgumentType]
_WarmupLoader.add_implicit_resolver(  # pyright: ignore[reportUnknownMemberType]
    _NULL, re.compile(r"^(?:~|null|Null|NULL|)$"), ["~", "n", "N", ""]
)


def _load(text: str) -> object:
    loader = _WarmupLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()  # pyright: ignore[reportUnknownMemberType]


class WarmupItem(NamedTuple):
    """One validated payload and where it came from."""

    file: str
    position: int
    kind: MemoryKind
    model: BaseModel
    item_id: UUID

    @property
    def location(self) -> str:
        """``file:kind[index]``."""
        return f"{self.file}:{self.kind.name}[{self.position}]"


class _Errors(list[InitErrorDetails]):
    def add(self, loc: Loc, message: str, value: object) -> None:
        error = PydanticCustomError("warmup_item_invalid", "{message}", {"message": message})
        self.append({"type": error, "loc": loc, "input": value})


class WarmupFiles(NamedTuple):
    """The items to warm up, and the hand-written copies their dump copies shadowed."""

    items: list[WarmupItem]
    shadowed: list[WarmupShadow]


def load_warmup_items(kb: KnowledgeBase) -> WarmupFiles:
    """Every item in ``warmup.path``'s ``*.yaml``/``*.yml`` files, in sorted path then file order.

    Dotfiles are skipped; any other entry, a subdirectory included, is an error. An item in
    its own dump file (``dump_file_name``) is the only copy returned; a differing copy it
    drops is listed in ``shadowed``.

    Raises:
        WarmupDirectoryMissing: ``warmup.path`` is not a directory, or cannot be listed.
        WarmupDirectoryEmpty: no file holds an item, and none is bad.
        pydantic.ValidationError: every bad file, kind, payload and duplicate key, each
            at ``loc`` ``(file, kind, index, ...)`` (shorter for a file- or kind-wide one).
    """
    root = kb.settings.warmup.path
    if not root.is_dir():
        msg = f"warm-up directory {root.absolute()} does not exist"
        raise WarmupDirectoryMissing(msg)
    try:
        entries = sorted(root.iterdir())
    except OSError as exc:
        msg = f"warm-up directory {root.absolute()} is unreadable: {exc.strerror}"
        raise WarmupDirectoryMissing(msg) from exc
    errors = _Errors()
    items: list[WarmupItem] = []
    for path in entries:
        if path.name.startswith("."):
            continue
        if path.suffix not in _SUFFIXES:
            errors.add((path.name,), "not a .yaml file; warm-up does not read it", None)
            continue
        if not path.is_file():
            errors.add((path.name,), "not a regular file; warm-up does not read it", None)
            continue
        items.extend(_file_items(kb, path, errors))
    items, shadowed = _resolve_duplicates(items, errors)
    if errors:
        title = "warmup_memory"
        raise ValidationError.from_exception_data(title, errors)
    if not items:
        msg = f"warm-up directory {root.resolve()} holds no items in *.yaml/*.yml files"
        raise WarmupDirectoryEmpty(msg)
    return WarmupFiles(items, shadowed)


def _file_items(kb: KnowledgeBase, path: Path, errors: _Errors) -> list[WarmupItem]:
    file = path.name
    try:
        text = path.read_bytes().decode()
    except (OSError, UnicodeDecodeError) as exc:
        errors.add((file,), f"not readable as UTF-8 text: {exc}", None)
        return []
    try:
        content = _load(text)
    except yaml.YAMLError as exc:
        errors.add((file,), f"not valid YAML: {exc}", None)
        return []
    if content is None:
        return []
    if not isinstance(content, Mapping):
        errors.add((file,), "must map kind names to lists of payloads", None)
        return []
    items: list[WarmupItem] = []
    for name, payloads in content.items():  # pyright: ignore[reportUnknownVariableType]
        items.extend(_kind_items(kb, file, str(name), payloads, errors))  # pyright: ignore[reportUnknownArgumentType]
    return items


def _kind_items(
    kb: KnowledgeBase, file: str, name: str, payloads: object, errors: _Errors
) -> list[WarmupItem]:
    try:
        kb.kinds.get(name)
    except UnknownKind as exc:
        errors.add((file, name), str(exc), None)
        return []
    if not isinstance(payloads, list):
        errors.add((file, name), "must be a list of payloads", None)
        return []
    items: list[WarmupItem] = []
    entries: list[object] = payloads  # pyright: ignore[reportUnknownVariableType]
    for index, payload in enumerate(entries):
        item = _item(kb, (file, name, index), payload, errors)
        if item is not None:
            items.append(item)
    return items


def _item(
    kb: KnowledgeBase, loc: tuple[str, str, int], payload: object, errors: _Errors
) -> WarmupItem | None:
    file, name, index = loc
    if not isinstance(payload, Mapping):
        errors.add(loc, "must be a mapping of payload fields", None)
        return None
    fields = kb.kinds.get(name).payload_model.model_fields
    unknown = [key for key in payload if key not in fields]  # pyright: ignore[reportUnknownVariableType]
    for key in unknown:  # pyright: ignore[reportUnknownVariableType]
        errors.add((*loc, str(key)), f"not a {name} field; expected one of {sorted(fields)}", None)  # pyright: ignore[reportUnknownArgumentType]
    if unknown:
        return None
    try:
        kind, model = validate_payload(kb, name, payload)  # pyright: ignore[reportUnknownArgumentType]
    except ValidationError as exc:
        for error in exc.errors():
            errors.add((*loc, *error["loc"]), error["msg"], error["input"])
        return None
    return WarmupItem(file, index, kind, model, item_id_of(kind, model))


def _resolve_duplicates(
    items: list[WarmupItem], errors: _Errors
) -> tuple[list[WarmupItem], list[WarmupShadow]]:
    """A copy in the item's own dump file drops every other; any remaining repeat is an error.

    A second copy inside the dump file itself is a repeat too, not a silent last-wins.
    Also returns each dropped copy whose payload differs from its dump copy's.
    """
    dumped: dict[UUID, WarmupItem] = {}
    for item in items:
        if _in_own_dump(item):
            dumped.setdefault(item.item_id, item)
    kept: list[WarmupItem] = []
    shadowed: list[WarmupShadow] = []
    for item in items:
        dump = dumped.get(item.item_id)
        if dump is None or _in_own_dump(item):
            kept.append(item)
        elif item.model.model_dump(mode="json") != dump.model.model_dump(mode="json"):
            shadowed.append(WarmupShadow(hand_written=item.location, dump=dump.location))
    first: dict[UUID, WarmupItem] = {}
    for item in kept:
        seen = first.setdefault(item.item_id, item)
        if seen is not item:
            # The key's text is the kind's own encoding; the two locations name it.
            message = f"same {item.kind.name} key as {seen.location}; {item.location} repeats it"
            errors.add((item.file, item.kind.name, item.position), message, None)
    return kept, shadowed


def _in_own_dump(item: WarmupItem) -> bool:
    return item.file == dump_file_name(item.kind.name, item.item_id)
