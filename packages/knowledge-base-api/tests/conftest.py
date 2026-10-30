"""``kb`` and ``client``: the app over a fake knowledge base (Qdrant ``:memory:``, MemoryHuey)."""

from __future__ import annotations

import pytest
from fake_kb import open_fake_kb
from fastapi.testclient import TestClient

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base_api.app import create_app


@pytest.fixture
def kb() -> KnowledgeBase:
    return open_fake_kb()


@pytest.fixture
def client(kb: KnowledgeBase) -> TestClient:
    return TestClient(create_app(kb))
