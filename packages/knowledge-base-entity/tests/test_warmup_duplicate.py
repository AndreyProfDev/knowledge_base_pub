"""A warm-up duplicate entity: the same ``name`` and ``type`` in two files."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_kb import open_fake_kb
from pydantic import ValidationError
from warmup_harness import warmup_settings, write_yaml

from tools_knowledge_base.operations import warmup_memory
from tools_knowledge_base_entity.kind import EntityKind


def test_the_same_name_and_type_in_two_files_names_both_locations(tmp_path: Path) -> None:
    entity = {"name": "Qdrant", "type": "system"}
    write_yaml(tmp_path / "a.yaml", {"entity": [{**entity, "description": "Vector store."}]})
    write_yaml(tmp_path / "b.yaml", {"entity": [{**entity, "description": "Prod store."}]})
    kb = open_fake_kb(EntityKind(), settings=warmup_settings(tmp_path))

    with pytest.raises(ValidationError) as caught:
        warmup_memory(kb)

    assert kb.huey.pending_count() == 0
    [error] = caught.value.errors()
    assert error["loc"] == ("b.yaml", "entity", 0)
    assert error["msg"] == "same entity key as a.yaml:entity[0]; b.yaml:entity[0] repeats it"
    assert "Qdrant" not in str(caught.value)
    assert "store." not in str(caught.value)
