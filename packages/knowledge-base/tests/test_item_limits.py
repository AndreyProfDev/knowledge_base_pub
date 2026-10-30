"""The per-kind character cap on an item's embed text: checked before anything is queued."""

from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner
from fake_kb import open_fake_kb, stored
from fake_kind import FakeKind
from fake_server import serve
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from knowledge_base_config import Environment
from tools_knowledge_base.cli.context import CliContext
from tools_knowledge_base.cli.main import build_cli
from tools_knowledge_base.configs.settings import (
    ItemLimitsSettings,
    KnowledgeBaseSettings,
    get_settings,
)
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.operations import list_memory_kinds, store_memory, update_memory_item

_HINT = "Split the tags across several fake items."


def _limited(default: int, **max_chars: int) -> KnowledgeBaseSettings:
    limits = ItemLimitsSettings(default_max_chars=default, max_chars=max_chars)
    return get_settings(Environment.TESTING).model_copy(update={"item_limits": limits})


def _payload(length: int) -> dict[str, object]:
    """A fake payload whose embed text, ``"t " + tag``, is ``length`` characters."""
    return {"title": "t", "tags": ["x" * (length - 2)]}


@pytest.fixture
def kb() -> KnowledgeBase:
    settings = _limited(30, alpha=10, beta=20)
    return open_fake_kb(FakeKind("alpha"), FakeKind("beta"), FakeKind("gamma"), settings=settings)


@pytest.mark.parametrize(("kind", "cap"), [("alpha", 10), ("beta", 20), ("gamma", 30)])
def test_each_kind_takes_its_own_cap_and_one_more_is_rejected(
    kb: KnowledgeBase, kind: str, cap: int
) -> None:
    assert store_memory(kb, kind, _payload(cap)).status == "queued"

    with pytest.raises(ValidationError) as caught:
        store_memory(kb, kind, _payload(cap + 1))

    [error] = caught.value.errors()
    assert error["type"] == "item_too_long"
    assert error["loc"] == ()
    assert error["msg"] == (
        f"{kind} item is {cap + 1} characters; the {kind} limit is {cap} "
        f"(counted over title and tags). {_HINT}"
    )


def test_over_cap_store_and_update_raise_before_anything_is_queued(kb: KnowledgeBase) -> None:
    item_id = stored(kb, "t", kind="alpha").item_id

    with pytest.raises(ValidationError, match="item_too_long"):
        store_memory(kb, "alpha", _payload(11))
    with pytest.raises(ValidationError, match="item_too_long"):
        update_memory_item(kb, "alpha", item_id, _payload(11))

    assert kb.huey.pending_count() == 0


def test_the_cap_is_checked_before_the_token_limit() -> None:
    # 17 words is over the fake embedder's 16 tokens, and 33 characters over the cap.
    kb = open_fake_kb(settings=_limited(32))

    with pytest.raises(ValidationError) as caught:
        store_memory(kb, "fake", {"title": "t", "tags": ["x"] * 16})

    assert caught.value.errors()[0]["type"] == "item_too_long"


@pytest.mark.parametrize("bad", [{"max_chars": {"knowledge": 0}}, {"default_max_chars": 0}])
def test_a_cap_below_one_fails_settings_validation(bad: dict[str, object]) -> None:
    configured = get_settings(Environment.TESTING).model_dump(mode="json")
    configured["item_limits"] = {"default_max_chars": 500, "max_chars": {}, **bad}

    with pytest.raises(ValidationError, match=r"item_limits\.(max_chars\.knowledge|default)"):
        KnowledgeBaseSettings.model_validate(configured)


def test_list_memory_kinds_gives_each_kinds_cap(kb: KnowledgeBase) -> None:
    caps = {schema.name: schema.max_chars for schema in list_memory_kinds(kb)}

    assert caps == {"alpha": 10, "beta": 20, "gamma": 30}


def test_the_store_and_update_tools_state_the_cap(kb: KnowledgeBase) -> None:
    tools = {tool.name: tool for tool in asyncio.run(serve(kb).list_tools())}

    for name in ("store_beta", "update_beta"):
        assert "At most 20 characters in total, counted over title and tags." in (
            tools[name].description or ""
        )


def test_an_over_cap_tool_call_is_an_error_naming_count_cap_and_hint(kb: KnowledgeBase) -> None:
    with pytest.raises(ToolError) as caught:
        asyncio.run(serve(kb).call_tool("store_alpha", _payload(11)))

    message = str(caught.value)
    assert "alpha item is 11 characters; the alpha limit is 10" in message
    assert _HINT in message
    assert kb.huey.pending_count() == 0


def test_an_over_cap_cli_store_exits_1_with_the_message_on_stderr(kb: KnowledgeBase) -> None:
    result = CliRunner().invoke(
        build_cli(kb.kinds),
        ["--env", "testing", "store-alpha", "--title", "t", "--tags", "x" * 9],
        obj=CliContext(open_kb=lambda _env: kb),
    )

    assert result.exit_code == 1
    assert "alpha item is 11 characters; the alpha limit is 10" in result.stderr
    assert _HINT in result.stderr


def test_the_cli_kinds_command_prints_each_kinds_cap(kb: KnowledgeBase) -> None:
    result = CliRunner().invoke(
        build_cli(kb.kinds), ["--env", "testing", "kinds"], obj=CliContext(open_kb=lambda _env: kb)
    )

    assert result.exit_code == 0
    caps = [line.split(";")[0] for line in result.output.splitlines()]
    assert caps == [
        "alpha: at most 10 characters",
        "beta: at most 20 characters",
        "gamma: at most 30 characters",
    ]
