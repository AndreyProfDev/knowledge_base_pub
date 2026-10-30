"""``/warmup``: 200 with the report, 422 per item, 404 missing directory or run, 503 partial.

Also a DELETE whose dump-file removal cannot be queued: 500 with the detail.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fake_kb import open_fake_kb, stored
from fake_kind import FakeKind
from fastapi.testclient import TestClient
from huey import Huey  # pyright: ignore[reportMissingTypeStubs]
from warmup_harness import FailingHuey, UnrecordableHuey, fake_items, warmup_settings, write_yaml

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import DumpRemovalNotQueued, WarmupPartiallyQueued
from tools_knowledge_base.operations.warmup_progress import WarmupRequest, WarmupRun, record_run
from tools_knowledge_base.queue import drain
from tools_knowledge_base_api.app import create_app


def _client(path: Path, huey: Huey | None = None) -> tuple[TestClient, KnowledgeBase]:
    kb = open_fake_kb(FakeKind("fake"), huey=huey, settings=warmup_settings(path))
    return TestClient(create_app(kb)), kb


def test_post_queues_the_items_and_get_follows_them(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two", "three")})
    client, kb = _client(tmp_path)

    report = client.post("/warmup")

    assert report.status_code == 200
    body = report.json()
    assert body["kinds"] == {"fake": {"queued": 3, "unchanged": 0}}
    assert body["total_queued"] == 3
    url = f"/warmup/{body['run_id']}"
    pending = client.get(url).json()
    assert (pending["total"], pending["done"], pending["pending"]) == (3, 0, 3)
    assert pending["finished"] is False
    drain(kb.huey)
    finished = client.get(url).json()
    assert (finished["done"], finished["pending"], finished["finished"]) == (3, 0, True)


def test_a_bad_item_is_a_422_located_at_file_kind_and_index(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": [*fake_items("ok"), {"tags": ["a"]}]})

    response = _client(tmp_path)[0].post("/warmup")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert [error["loc"][:3] for error in detail] == [["a.yaml", "fake", 1]]
    assert all("input" not in error for error in detail)


def test_a_duplicate_key_is_a_422_naming_both_locations(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    write_yaml(tmp_path / "b.yaml", {"fake": fake_items("one")})

    detail = _client(tmp_path)[0].post("/warmup").json()["detail"]

    assert [error["loc"] for error in detail] == [["b.yaml", "fake", 0]]
    assert "a.yaml:fake[0]" in detail[0]["msg"]
    assert "b.yaml:fake[0]" in detail[0]["msg"]


def test_a_missing_directory_is_a_404_naming_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent"

    response = _client(missing)[0].post("/warmup")

    assert response.status_code == 404
    assert str(missing) in response.json()["detail"]


def test_a_directory_holding_no_items_is_a_404_naming_it(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*\n", encoding="utf-8")

    response = _client(tmp_path)[0].post("/warmup")

    assert response.status_code == 404
    assert f"{tmp_path.resolve()} holds no items" in response.json()["detail"]


def test_an_enqueue_failing_partway_is_a_503_naming_the_followable_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    client, _ = _client(tmp_path, huey=FailingHuey(1))

    with caplog.at_level(logging.ERROR, logger="tools_knowledge_base_api.app"):
        response = client.post("/warmup")

    assert response.status_code == 503
    detail = response.json()["detail"]
    match = re.fullmatch(
        r"warm-up run (\S+) stopped after queueing 1 requests and was recorded: OSError: .*", detail
    )
    assert match is not None, detail
    run_id = match.group(1)
    [record] = [r for r in caplog.records if r.name == "tools_knowledge_base_api.app"]
    assert record.levelno == logging.ERROR
    assert record.getMessage() == f"warm-up run {run_id} failed on the queue"
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], WarmupPartiallyQueued)
    assert isinstance(record.exc_info[1].__cause__, OSError)
    assert client.get(f"/warmup/{run_id}").json()["total"] == 1


def test_a_delete_whose_forget_cannot_be_queued_is_a_500_saying_the_item_is_gone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client, kb = _client(tmp_path, huey=FailingHuey(1))
    accepted = stored(kb, "one")

    with caplog.at_level(logging.ERROR, logger="tools_knowledge_base_api.app"):
        response = client.delete(f"/memory/fake/{accepted.item_id}")

    assert response.status_code == 500
    assert f"fake item {accepted.item_id} deleted; dump file" in response.json()["detail"]
    [record] = [r for r in caplog.records if r.name == "tools_knowledge_base_api.app"]
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], DumpRemovalNotQueued)
    assert client.get(f"/memory/fake/{accepted.item_id}").status_code == 404


def test_a_run_that_cannot_be_recorded_is_a_503_not_a_500(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    client, _ = _client(tmp_path, huey=UnrecordableHuey("warmup:"))

    response = client.post("/warmup")

    assert response.status_code == 503
    assert re.fullmatch(
        r"warm-up run \S+ queued 2 requests but could not be recorded: OSError: .*",
        response.json()["detail"],
    )


def test_an_unknown_run_is_a_404(tmp_path: Path) -> None:
    response = _client(tmp_path)[0].get("/warmup/no-such-run")

    assert response.status_code == 404
    assert "no-such-run" in response.json()["detail"]


def test_a_known_run_with_a_never_issued_request_is_a_500_not_a_404(tmp_path: Path) -> None:
    kb = open_fake_kb(FakeKind("fake"), settings=warmup_settings(tmp_path))
    request = WarmupRequest(request_id="ghost", item_id=uuid4(), kind="fake")
    record_run(kb, "run-1", WarmupRun(requests=[request], unchanged=0))

    response = TestClient(create_app(kb), raise_server_exceptions=False).get("/warmup/run-1")

    assert response.status_code == 500
