"""The registered tools called through the server, as a client calls them."""

from __future__ import annotations

import asyncio

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from fake_server import call, serve
from mcp.server.mcpserver.exceptions import ToolError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.queue import drain


@pytest.fixture
def kb() -> KnowledgeBase:
    return open_fake_kb(FakeKind("alpha"), FakeKind("beta"))


def test_every_tool_round_trips_through_the_server(kb: KnowledgeBase) -> None:
    server = serve(kb)

    accepted = call(server, "store_alpha", title="first", tags=["x"])
    drain(kb.huey)
    request = call(server, "get_memory_request", request_id=accepted["request_id"])
    assert request["status"] == "done"
    item_id = str(accepted["item_id"])
    hits = call(server, "search_memory", query="first", kind="alpha")["result"]
    assert [hit["id"] for hit in hits] == [item_id]

    assert call(server, "get_alpha", id=item_id)["payload"] == {"title": "first", "tags": ["x"]}
    page = call(server, "list_alpha", limit=10)
    assert [i["id"] for i in page["items"]] == [item_id]
    call(server, "update_alpha", id=item_id, title="first", tags=["y"])
    drain(kb.huey)
    assert call(server, "get_alpha", id=item_id)["payload"] == {"title": "first", "tags": ["y"]}
    deleted = call(server, "delete_alpha", id=item_id)
    assert call(server, "list_alpha")["items"] == []
    drain(kb.huey)
    request = call(server, "get_memory_request", request_id=deleted["request_id"])
    assert request["status"] == "done"


def test_an_update_changing_the_identity_moves_the_item_to_the_returned_id(
    kb: KnowledgeBase,
) -> None:
    """What the ``update_*`` description promises: the returned id, not ``id``, from then on."""
    server = serve(kb)
    old_id = call(server, "store_alpha", title="first", tags=[])["item_id"]
    drain(kb.huey)

    new_id = call(server, "update_alpha", id=old_id, title="renamed", tags=[])["item_id"]
    drain(kb.huey)

    assert new_id != old_id
    assert call(server, "get_alpha", id=new_id)["payload"]["title"] == "renamed"
    with pytest.raises(ToolError, match=f"no alpha item has id {old_id}"):
        asyncio.run(server.call_tool("get_alpha", {"id": old_id}))


def test_search_passes_query_kind_top_k_and_min_score_through(kb: KnowledgeBase) -> None:
    server = serve(kb)
    first = call(server, "store_alpha", title="first", tags=[])["item_id"]
    second = call(server, "store_beta", title="second", tags=[])["item_id"]
    drain(kb.huey)

    def ids(**arguments: object) -> list[str]:
        return [hit["id"] for hit in call(server, "search_memory", **arguments)["result"]]

    assert ids(query="second", top_k=1) == [str(second)]
    assert ids(query="second", kind="alpha") == [str(first)]
    assert ids(query="second", min_score=0.99) == [str(second)]


def test_list_pages_by_limit_and_cursor(kb: KnowledgeBase) -> None:
    server = serve(kb)
    stored = {call(server, "store_alpha", title=title, tags=[])["item_id"] for title in "abc"}
    drain(kb.huey)

    assert {item["id"] for item in call(server, "list_alpha")["items"]} == stored
    first = call(server, "list_alpha", limit=2)
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    rest = call(server, "list_alpha", limit=2, cursor=first["next_cursor"])
    assert rest["next_cursor"] is None

    assert {item["id"] for item in first["items"] + rest["items"]} == stored
