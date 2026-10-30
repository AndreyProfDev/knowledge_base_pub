"""``register``'s two rules: plain payload fields, and tool names that may mount."""

from __future__ import annotations

from typing import Any

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from fake_server import keyed_settings
from mcp.server import MCPServer
from pydantic import BaseModel, ConfigDict, Field, create_model

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.registration import register


def _refused(kb: KnowledgeBase, server: MCPServer) -> str:
    """``register``'s refusal message."""
    with pytest.raises(KnowledgeBaseError) as raised:
        register(server, settings=keyed_settings(), open_kb=lambda _settings: kb)
    return str(raised.value)


def _payload(field: str, value: object = ..., **config: Any) -> type[BaseModel]:
    """A payload of one ``str`` field ``field``, defined by ``value``."""
    fields: dict[str, Any] = {field: (str, value)}
    return create_model("Payload", __config__=ConfigDict(**config), **fields)


@pytest.mark.parametrize(
    ("payload", "field", "condition"),
    [
        (_payload("ref", Field(alias="reference")), "ref", "alias"),
        (_payload("ref", Field(validation_alias="reference")), "ref", "alias"),
        (_payload("ref", Field(serialization_alias="Ref")), "ref", "alias"),
        (_payload("ref", alias_generator=str.upper), "ref", "alias"),
        (_payload("ref", Field(exclude=True)), "ref", "excluded"),
        (_payload("bad-name"), "bad-name", "not a Python identifier"),
        (_payload("from"), "from", "not a Python identifier"),
        (_payload("id"), "id", "item id"),
    ],
    ids=[
        "alias",
        "validation_alias",
        "serialization_alias",
        "alias_generator",
        "exclude",
        "non-identifier",
        "keyword",
        "id",
    ],
)
def test_a_payload_field_that_is_not_plain_names_kind_field_and_condition(
    payload: type[BaseModel], field: str, condition: str
) -> None:
    """``alpha`` sorts first and is fine; ``clash`` is refused."""
    clashing = FakeKind("clash")
    clashing.payload_model = payload
    message = _refused(open_fake_kb(FakeKind("alpha"), clashing), MCPServer("test"))
    assert f"kind 'clash' payload field {field!r} is not plain" in message
    assert condition in message


def test_a_kind_named_memory_request_does_not_shadow_the_generic_tool() -> None:
    message = _refused(open_fake_kb(FakeKind("memory_request")), MCPServer("test"))
    assert "repeated: 'get_memory_request'" in message


def test_a_kind_name_with_a_space_is_not_a_valid_mcp_tool_name() -> None:
    message = _refused(open_fake_kb(FakeKind("bad name")), MCPServer("test"))
    assert "not a valid MCP tool name: 'store_bad name'" in message
