from __future__ import annotations

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb
from fake_server import keyed_settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from stevedore import ExtensionManager

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base_api.app import main
from tools_knowledge_base_api.configs.settings import get_settings


def _never_run(_app: FastAPI, /, *, host: str, port: int) -> None:
    msg = "served a knowledge base that cannot serve a write"
    raise AssertionError(msg)


def test_main_serves_the_opened_knowledge_base_on_the_settings() -> None:
    kb = open_fake_kb(settings=keyed_settings())
    served: list[tuple[FastAPI, str, int]] = []

    def serve(app: FastAPI, /, *, host: str, port: int) -> None:
        served.append((app, host, port))

    main(kb_settings=keyed_settings(), open_kb=lambda _s: kb, run=serve)

    ((app, host, port),) = served
    settings = get_settings(Environment.TESTING)
    assert (host, port) == (settings.host, settings.port)
    # TestClient's Host is allowed by the testing overlay only.
    assert TestClient(app).get("/kinds").json()[0]["name"] == "fake"


def test_main_opens_the_configured_knowledge_base_by_default() -> None:
    """Qdrant in memory, every installed kind; keyed, as the testing overlay is not."""
    served: list[FastAPI] = []

    def serve(app: FastAPI, /, *, host: str, port: int) -> None:
        served.append(app)

    main(kb_settings=keyed_settings(), run=serve)

    (app,) = served
    names = {kind["name"] for kind in TestClient(app).get("/kinds").json()}
    assert {"entity", "knowledge", "workflow"} <= names


def test_main_refuses_a_keyless_embedder_before_opening() -> None:
    def must_not_open(_settings: KnowledgeBaseSettings) -> KnowledgeBase:
        pytest.fail("must not open")

    with pytest.raises(KnowledgeBaseError, match=r"'openai-small'.*empty api_key"):
        main(kb_settings=keyed_settings(api_key=""), open_kb=must_not_open, run=_never_run)


def test_main_reads_the_tools_env_settings_by_default() -> None:
    """The testing overlay's embedder is keyless, so the default path refuses it."""

    def must_not_open(_settings: KnowledgeBaseSettings) -> KnowledgeBase:
        pytest.fail("must not open")

    with pytest.raises(KnowledgeBaseError, match="empty api_key"):
        main(open_kb=must_not_open, run=_never_run)


def test_main_refuses_a_knowledge_base_with_no_kinds() -> None:
    def no_kinds(settings: KnowledgeBaseSettings) -> KnowledgeBase:
        empty = KindRegistry(ExtensionManager[MemoryKind].make_test_instance([]))
        return open_knowledge_base(settings, embedder=FakeEmbedder(), kinds=empty)

    with pytest.raises(KnowledgeBaseError, match="no memory kinds installed"):
        main(kb_settings=keyed_settings(), open_kb=no_kinds, run=_never_run)
