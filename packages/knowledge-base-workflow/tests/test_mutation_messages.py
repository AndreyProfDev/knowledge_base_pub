"""The exact words a rejected workflow field is reported with."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tools_knowledge_base_workflow.kind import WorkflowPayload


def test_a_multi_line_step_carries_the_exact_message() -> None:
    with pytest.raises(ValidationError) as caught:
        WorkflowPayload.model_validate({"name": "x", "steps": ["a\fb"]})

    assert [error["msg"] for error in caught.value.errors()] == [
        "Value error, must be one non-blank line"
    ]
