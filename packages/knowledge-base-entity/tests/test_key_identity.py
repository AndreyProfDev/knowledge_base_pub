"""What the ``(name, type)`` key keeps apart: case, and every member of the type set."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from tools_knowledge_base_entity.kind import EntityKind, EntityPayload

TYPES = ["person", "system", "project", "concept", "organization", "tool"]


def test_the_type_set_is_exactly_the_six_documented_types() -> None:
    assert sorted(get_args(EntityPayload.model_fields["type"].annotation)) == sorted(TYPES)


@pytest.mark.parametrize("entity_type", TYPES)
def test_each_type_is_accepted_and_keyed_apart(entity_type: str) -> None:
    kind = EntityKind()
    payload = EntityPayload.model_validate({"name": "x", "type": entity_type, "description": "d"})
    others = {
        kind.key(EntityPayload.model_validate({"name": "x", "type": t, "description": "d"}))
        for t in TYPES
        if t != entity_type
    }

    assert kind.key(payload) not in others


def test_names_differing_only_in_case_are_different_entities() -> None:
    kind = EntityKind()

    assert kind.key(EntityPayload(name="Huey", type="tool", description="d")) != kind.key(
        EntityPayload(name="huey", type="tool", description="d")
    )


def test_an_uppercase_type_is_refused() -> None:
    with pytest.raises(ValidationError):
        EntityPayload.model_validate({"name": "x", "type": "Person", "description": "d"})
