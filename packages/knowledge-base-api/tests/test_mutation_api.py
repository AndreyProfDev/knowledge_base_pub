"""What the other suites left unasserted: the delete-failure log line."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fake_kb import open_fake_kb, stored
from fake_kind import FakeKind
from fastapi.testclient import TestClient
from warmup_harness import FailingHuey, warmup_settings

from tools_knowledge_base_api.app import create_app


def test_a_delete_whose_forget_cannot_be_queued_logs_what_happened(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    kb = open_fake_kb(FakeKind("fake"), huey=FailingHuey(1), settings=warmup_settings(tmp_path))
    accepted = stored(kb, "one")

    with caplog.at_level(logging.ERROR, logger="tools_knowledge_base_api.app"):
        TestClient(create_app(kb)).delete(f"/memory/fake/{accepted.item_id}")

    assert [r.getMessage() for r in caplog.records if r.name == "tools_knowledge_base_api.app"] == [
        "delete succeeded but its dump removal was not queued"
    ]
