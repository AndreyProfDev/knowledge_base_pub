"""The exact words a rejected entity field is reported with."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tools_knowledge_base_entity.kind import EntityPayload


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"name": "a\nb", "type": "person", "description": "d"},
            "Value error, must be one non-blank line",
        ),
        (
            {"name": "x", "type": "tool", "description": " \t"},
            "Value error, must not be blank",
        ),
    ],
)
def test_a_rejected_field_carries_its_exact_message(payload: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError) as caught:
        EntityPayload.model_validate(payload)

    assert [error["msg"] for error in caught.value.errors()] == [message]
