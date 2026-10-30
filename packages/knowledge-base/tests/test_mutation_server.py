"""What a client reads off the tools word for word, and the embedder's no-key refusal."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from fake_server import keyed_settings, serve
from mcp.server import MCPServer
from mcp.types import Tool
from pydantic import BaseModel, Field, create_model

from tools_knowledge_base.embeddings import OpenAIEmbedder
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.registration import register


def _listed() -> dict[str, Tool]:
    server = serve(open_fake_kb(FakeKind("alpha"), FakeKind("beta")))
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _description(listed: dict[str, Tool], name: str) -> str:
    return listed[name].description or ""


def test_the_kind_tool_descriptions_word_for_word() -> None:
    listed = _listed()

    assert _description(listed, "store_alpha").startswith(
        "Store one alpha item; storing one with the same identity updates it in place. "
        "Returns the request id"
    )
    assert _description(listed, "get_alpha") == "Get the alpha item `id`."
    assert _description(listed, "list_alpha") == (
        "List alpha items, a page at a time: pass `next_cursor` back as `cursor`."
    )
    assert _description(listed, "delete_alpha") == (
        "Delete the alpha item `id` at once. Returns the request id removing its warm-up "
        "dump file: poll it with get_memory_request; until it is done the file can bring "
        "the item back."
    )


def test_a_list_takes_50_items_unless_told_otherwise() -> None:
    limit = _listed()["list_alpha"].input_schema["properties"]["limit"]

    assert limit["default"] == 50


def test_the_generic_tool_descriptions_word_for_word() -> None:
    listed = _listed()

    assert _description(listed, "search_memory") == (
        "Search the stored memories semantically for `query`, best match first. `kind` "
        "limits the search to one kind, one of: alpha, beta; omitted, every kind is "
        "searched. `top_k` caps the number of hits and `min_score` drops weaker ones; both "
        "default to the server's configuration. `min_score` is a cosine similarity; "
        "higher is closer."
    )
    assert _description(listed, "get_memory_request") == (
        "Report a queued request by the `request_id` a store, update or delete returned: "
        "`queued` until the worker has run it, then `done`, or `failed` with the error."
    )
    warmup = _description(listed, "warmup_memory")
    assert warmup.startswith("Queue every item in the server's warm-up directory of YAML")
    assert warmup.endswith("Poll get_warmup_progress with the `run_id`.")


def test_search_types_its_query_and_min_score() -> None:
    search = _listed()["search_memory"].input_schema["properties"]

    assert search["query"] == {"title": "Query", "type": "string"}
    assert {"type": "number"} in search["min_score"]["anyOf"]


def _payload(field: str, value: object = ...) -> type[BaseModel]:
    fields: dict[str, Any] = {field: (str, value)}
    return create_model("Payload", **fields)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            _payload("ref", Field(alias="reference")),
            "it has an alias, so its tool parameter, payload and output names differ",
        ),
        (
            _payload("ref", Field(exclude=True)),
            "it is excluded, so model_dump drops it from every stored payload",
        ),
        (
            _payload("from"),
            "its name is not a Python identifier, so it cannot be a tool parameter",
        ),
        (_payload("id"), "it is called id, which the tools take as the item id"),
    ],
    ids=["alias", "exclude", "keyword", "id"],
)
def test_a_refused_payload_field_gives_its_whole_reason(
    payload: type[BaseModel], reason: str
) -> None:
    kind = FakeKind("clash")
    kind.payload_model = payload
    kb = open_fake_kb(kind)

    with pytest.raises(KnowledgeBaseError) as raised:
        register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _settings: kb)

    assert str(raised.value).endswith(f"is not plain: {reason}")


def test_a_keyless_embedder_says_which_variable_to_set() -> None:
    config = keyed_settings(api_key="").embeddings.active_embedder

    with pytest.raises(KnowledgeBaseError) as raised:
        OpenAIEmbedder(config).count_tokens("sky")

    assert str(raised.value) == (
        f"embedder {config.model} at {config.base_url} has no api_key: set OPEN_AI_API_KEY"
    )
