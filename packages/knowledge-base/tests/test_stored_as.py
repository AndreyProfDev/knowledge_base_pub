"""The stored-item error's message."""

from __future__ import annotations

import pytest
from fake_kind import FakePayload

from tools_knowledge_base.errors import StoredItemInvalid, stored_as


def test_a_stored_item_error_names_where_and_the_errors_without_links() -> None:
    with pytest.raises(StoredItemInvalid) as error:
        stored_as(FakePayload, {"title": "sky"}, "item 7")

    message = str(error.value)
    assert message.startswith("item 7: [")
    assert "'tags'" in message
    assert "errors.pydantic.dev" not in message
