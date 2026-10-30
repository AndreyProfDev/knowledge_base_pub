"""The configured 500-character cap counts ``name: description``."""

from __future__ import annotations

import pytest
from fake_kb import open_fake_kb
from pydantic import ValidationError

from tools_knowledge_base.operations import store_memory
from tools_knowledge_base_entity.kind import EntityKind


def _entity(description_length: int) -> dict[str, object]:
    return {"name": "n", "type": "tool", "description": "d" * description_length}


def test_name_and_description_of_exactly_the_cap_are_stored_and_one_more_is_rejected() -> None:
    kb = open_fake_kb(EntityKind())

    # "n: " is 3 characters of the 500.
    assert store_memory(kb, "entity", _entity(497)).item_id

    with pytest.raises(ValidationError) as caught:
        store_memory(kb, "entity", _entity(498))

    assert caught.value.errors()[0]["msg"] == (
        "entity item is 501 characters; the entity limit is 500 "
        "(counted over name: description). Keep the description to what the entity is; "
        "store further facts about it as separate knowledge items."
    )
