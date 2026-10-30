"""A second ``POST /warmup`` over the three real kinds leaves every item unchanged."""

from __future__ import annotations

from pathlib import Path

from fake_kb import open_fake_kb
from fastapi.testclient import TestClient
from warmup_harness import warmup_settings, write_yaml

from tools_knowledge_base.queue import drain
from tools_knowledge_base_api.app import create_app
from tools_knowledge_base_entity.kind import EntityKind
from tools_knowledge_base_knowledge.kind import KnowledgeKind
from tools_knowledge_base_workflow.kind import WorkflowKind

_FILES = {
    "knowledge": [{"category": "preference", "content": "Prefers uv over pip."}],
    "entity": [{"name": "Qdrant", "type": "system", "description": "Vector store in prod."}],
    "workflow": [{"name": "Release a tool package", "steps": ["make check", "bump the version"]}],
}


def test_a_second_run_over_the_real_kinds_queues_nothing(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", _FILES)
    kinds = (KnowledgeKind(), EntityKind(), WorkflowKind())
    kb = open_fake_kb(*kinds, settings=warmup_settings(tmp_path))
    client = TestClient(create_app(kb))

    first = client.post("/warmup").json()
    drain(kb.huey)
    second = client.post("/warmup").json()

    assert first["kinds"] == {name: {"queued": 1, "unchanged": 0} for name in _FILES}
    assert second["kinds"] == {name: {"queued": 0, "unchanged": 1} for name in _FILES}
    assert second["total_queued"] == 0
    assert kb.huey.pending_count() == 0
