"""``register``: the generic tools and five per installed kind, annotated and described."""

from __future__ import annotations

import asyncio

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from fake_server import keyed_settings, serve
from mcp.server import MCPServer
from mcp.types import Tool, ToolAnnotations
from pydantic import BaseModel, ConfigDict, PydanticInvalidForJsonSchema
from stevedore import ExtensionManager

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base.models import MemoryItem, MemoryPage, WriteAccepted
from tools_knowledge_base.operations import MAX_LIMIT
from tools_knowledge_base.registration import register

READ_ONLY = ToolAnnotations(read_only_hint=True)
DESTRUCTIVE = ToolAnnotations(destructive_hint=True, idempotent_hint=True)
# The fake kind has no ``item_limits`` entry, so the base overlay's default applies.
_CAP = " At most 500 characters in total, counted over title and tags."


@pytest.fixture
def kb() -> KnowledgeBase:
    return open_fake_kb(FakeKind("alpha"), FakeKind("beta"))


def _listed(server: MCPServer) -> dict[str, Tool]:
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _must_not_open(_settings: KnowledgeBaseSettings) -> KnowledgeBase:
    pytest.fail("must not open")


def test_tools_appear_for_each_kind_with_their_annotations(kb: KnowledgeBase) -> None:
    server = MCPServer("test")
    returned = register(server, settings=keyed_settings(), open_kb=lambda _settings: kb)
    listed = _listed(server)

    expected: dict[str, ToolAnnotations | None] = {
        "search_memory": READ_ONLY,
        "get_memory_request": READ_ONLY,
        "warmup_memory": ToolAnnotations(destructive_hint=True, idempotent_hint=True),
        "get_warmup_progress": READ_ONLY,
    }
    for kind in ("alpha", "beta"):
        expected |= {
            f"store_{kind}": None,
            f"update_{kind}": None,
            f"get_{kind}": READ_ONLY,
            f"list_{kind}": READ_ONLY,
            f"delete_{kind}": DESTRUCTIVE,
        }
    assert {name: tool.annotations for name, tool in listed.items()} == expected
    # Discovery reads the tool names, and finds duplicates, in what register returns.
    assert {fn.__name__ for fn in returned} == set(listed)

    store = listed["store_alpha"].input_schema
    assert set(store["properties"]) == {"title", "tags"}
    assert set(store["required"]) == {"title", "tags"}
    update = listed["update_alpha"].input_schema
    assert set(update["required"]) == {"id", "title", "tags"}
    assert store["properties"]["title"]["description"] == "What the item is called."
    assert store["properties"]["title"]["maxLength"] == 40
    listing = listed["list_alpha"].input_schema["properties"]
    assert (listing["limit"]["minimum"], listing["limit"]["maximum"]) == (1, MAX_LIMIT)
    assert {"format": "uuid", "type": "string"} in listing["cursor"]["anyOf"]


def test_search_takes_an_installed_kind_and_a_positive_top_k(kb: KnowledgeBase) -> None:
    search = _listed(serve(kb))["search_memory"].input_schema["properties"]
    assert "kb" not in search
    assert {"enum": ["alpha", "beta"], "type": "string"} in search["kind"]["anyOf"]
    top_k = {"maximum": MAX_LIMIT, "minimum": 1, "type": "integer"}
    assert top_k in search["top_k"]["anyOf"]


def test_the_schemas_a_client_reads(kb: KnowledgeBase) -> None:
    listed = _listed(serve(kb))
    item_id = {"format": "uuid", "title": "Id", "type": "string"}
    for name in ("get_alpha", "delete_alpha"):
        assert listed[name].input_schema["properties"] == {"id": item_id}, name
    assert listed["update_alpha"].input_schema["properties"]["id"] == item_id
    for name, model in (
        ("store_alpha", WriteAccepted),
        ("update_alpha", WriteAccepted),
        ("get_alpha", MemoryItem),
        ("list_alpha", MemoryPage),
    ):
        assert listed[name].output_schema == model.model_json_schema(), name


def test_the_descriptions_a_client_reads(kb: KnowledgeBase) -> None:
    listed = _listed(serve(kb))
    store = listed["store_alpha"].description or ""
    assert store.endswith(f"One fake item; `title` is its identity.{_CAP}")
    assert "same identity updates it in place" in store
    update = listed["update_alpha"].description or ""
    assert "differs from `id` when the identity fields change" in update
    assert update.endswith(_CAP)
    search = listed["search_memory"].description or ""
    assert "one of: alpha, beta" in search
    assert "`min_score` is a cosine similarity; higher is closer" in search
    assert "Raises" not in search
    request = listed["get_memory_request"].description or ""
    assert "`queued` until the worker has run it" in request
    assert "Raises" not in request


class _UndocumentedPayload(BaseModel):
    title: str


def test_an_undocumented_payload_leaves_no_trailing_space() -> None:
    bare = FakeKind("bare")
    bare.payload_model = _UndocumentedPayload
    store = _listed(serve(open_fake_kb(bare)))["store_bare"].description or ""
    assert store.endswith(f"and the item id.{_CAP}")


class _MultiLinePayload(BaseModel):
    """First line.

    Second line, indented in source.
    """

    title: str


def test_a_multi_line_payload_docstring_is_dedented() -> None:
    lined = FakeKind("lined")
    lined.payload_model = _MultiLinePayload
    store = _listed(serve(open_fake_kb(lined)))["store_lined"].description or ""
    assert store.endswith(f"First line.\n\nSecond line, indented in source.{_CAP}")


def test_a_keyless_embedder_declines_registration() -> None:
    """An empty key, as an unset ``OPEN_AI_API_KEY`` leaves it."""
    with pytest.raises(
        KnowledgeBaseError, match=r"'openai-small'.* empty api_key: set OPEN_AI_API_KEY"
    ):
        register(MCPServer("test"), settings=keyed_settings(api_key=""), open_kb=_must_not_open)


def test_a_keyless_self_hosted_embedder_names_its_own_api_key() -> None:
    with pytest.raises(KnowledgeBaseError) as raised:
        register(
            MCPServer("test"), settings=keyed_settings("bge-m3", api_key=""), open_kb=_must_not_open
        )
    assert "'bge-m3'" in str(raised.value)
    assert "set embeddings.embedders.bge-m3.api_key" in str(raised.value)
    assert "OPEN_AI_API_KEY" not in str(raised.value)


def test_no_installed_kind_declines_registration() -> None:
    empty = KindRegistry(ExtensionManager[MemoryKind].make_test_instance([]))
    kb = open_knowledge_base(keyed_settings(), embedder=FakeEmbedder(), kinds=empty)

    with pytest.raises(KnowledgeBaseError, match="no memory kinds installed"):
        register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _settings: kb)


class _Opaque:
    """A type pydantic validates by isinstance but cannot describe in a JSON schema."""


class _UnschemablePayload(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    blob: _Opaque


def test_a_tool_the_sdk_cannot_describe_declines_registration() -> None:
    broken = FakeKind("zbroken")
    broken.payload_model = _UnschemablePayload
    kb = open_fake_kb(FakeKind("alpha"), broken)

    with pytest.raises(PydanticInvalidForJsonSchema, match="_Opaque"):
        register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _settings: kb)
