from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fake_kind import FakeKind, FakePayload
from pydantic import ValidationError

from tools_knowledge_base.errors import StoredItemInvalid
from tools_knowledge_base.models import MemoryHit, MemoryItem
from tools_knowledge_base.operations.items import memory_item
from tools_knowledge_base.store.protocol import Item

_ID = UUID("00000000-0000-0000-0000-000000000001")
_AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_an_item_dumps_its_kind_payload_fields() -> None:
    hit = MemoryHit(
        id=_ID, kind="fake", updated_at=_AT, payload=FakePayload(title="t", tags=["a"]), score=0.9
    )

    assert hit.model_dump(mode="json")["payload"] == {"title": "t", "tags": ["a"]}


def test_a_store_record_refuses_a_naive_updated_at() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Item(id=_ID, kind="fake", updated_at=datetime(2026, 1, 1), payload={})


def test_an_item_payload_schema_is_an_open_object() -> None:
    schema = MemoryItem.model_json_schema()

    assert schema["properties"]["payload"] == {"type": "object", "additionalProperties": True}


def test_a_stored_payload_its_kind_refuses_is_stored_item_invalid() -> None:
    drifted = Item(id=_ID, kind="fake", updated_at=_AT, payload={"title": "t", "colour": "red"})

    with pytest.raises(StoredItemInvalid, match=rf"fake item {_ID} .*'colour'") as raised:
        memory_item(FakeKind(), drifted)
    assert "'red'" not in str(raised.value)
    assert not isinstance(raised.value, ValidationError)
    assert isinstance(raised.value.__cause__, ValidationError)
