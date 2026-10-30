"""Operation errors map to 404 and 422; every 422 has FastAPI's own body shape."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import lancedb
import pytest
from fake_kb import lancedb_settings, open_fake_kb
from fastapi.testclient import TestClient
from pydantic import ValidationError

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import StoredItemInvalid
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base_api.app import create_app

# Fixed, not uuid4(): it lands in parametrize ids, which must match across processes
# (mutmut's forkserver collects in one process and runs each mutant in another).
_ABSENT = UUID("00000000-0000-4000-8000-000000000001")


def _refusals(
    client: TestClient, method: str, path: str, body: object = None
) -> list[dict[str, Any]]:
    """The 422's ``detail``, checked to be shaped as FastAPI's own validation errors."""
    response = client.request(method, path, json=body)
    assert response.status_code == 422
    detail: list[dict[str, Any]] = response.json()["detail"]
    assert detail
    for error in detail:
        assert {"loc", "msg", "type"} <= set(error)
        assert "url" not in error
        assert "input" not in error
    return detail


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/memory/nope"),
        ("PUT", f"/memory/nope/{_ABSENT}"),
        ("GET", f"/memory/nope/{_ABSENT}"),
        ("GET", "/memory/nope"),
        ("DELETE", f"/memory/nope/{_ABSENT}"),
        ("GET", "/search?q=x&kind=nope"),
    ],
)
def test_an_unknown_kind_is_404(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"title": "kettle", "tags": []})

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_an_absent_id_is_404(client: TestClient, method: str) -> None:
    response = client.request(method, f"/memory/fake/{_ABSENT}", json={"title": "k", "tags": []})

    assert response.status_code == 404
    assert str(_ABSENT) in response.json()["detail"]


def test_an_unknown_request_id_is_404(client: TestClient) -> None:
    assert client.get("/requests/no-such-request").status_code == 404


@pytest.mark.parametrize(
    ("payload", "loc"),
    [
        ({"title": "kettle"}, ["body", "tags"]),
        ({"title": "kettle", "tags": [], "colour": "red"}, ["body", "colour"]),
        ({"title": "x" * 41, "tags": []}, ["body", "title"]),
    ],
)
def test_a_payload_the_kind_refuses_is_422(
    client: TestClient, payload: dict[str, object], loc: list[str]
) -> None:
    (error,) = _refusals(client, "POST", "/memory/fake", payload)

    assert error["loc"] == loc


def test_a_non_object_body_is_fastapis_own_422(client: TestClient) -> None:
    (error,) = _refusals(client, "POST", "/memory/fake", ["kettle"])

    assert error["loc"] == ["body"]


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        (b'{"title": NaN, "tags": []}', ["body", "title"]),
        (b'{"title": 1e999, "tags": []}', ["body", "title"]),
        (b"[NaN]", ["body"]),
    ],
)
def test_a_non_finite_number_in_the_body_is_422_not_500(
    client: TestClient, body: bytes, loc: list[str]
) -> None:
    response = client.post(
        "/memory/fake", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [loc]


def test_an_over_limit_embed_text_is_422(client: TestClient) -> None:
    words = " ".join(f"w{i}" for i in range(17))

    (error,) = _refusals(client, "POST", "/memory/fake", {"title": "t", "tags": [words]})

    assert (error["type"], error["loc"]) == ("embed_text_rejected", ["body"])
    assert "tokens, over the embedder's" in error["msg"]


@pytest.mark.parametrize(
    ("path", "loc", "error_type"),
    [
        ("/memory/fake?limit=0", ["query", "limit"], "greater_than_equal"),
        ("/search?q=x&top_k=0", ["query", "top_k"], "greater_than_equal"),
        (f"/memory/fake?limit={2**63 - 1}", ["query", "limit"], "less_than_equal"),
        ("/search?q=x&top_k=1001", ["query", "top_k"], "less_than_equal"),
        ("/memory/fake?limit=abc", ["query", "limit"], "int_parsing"),
        ("/search?q=", ["query", "q"], "blank_query"),
        ("/search?q=%20", ["query", "q"], "blank_query"),
        ("/search?q=%1C", ["query", "q"], "blank_query"),
        ("/search?q=x&min_score=nan", ["query", "min_score"], "finite_number"),
    ],
)
def test_a_query_parameter_out_of_range_is_fastapis_own_422(
    client: TestClient, path: str, loc: list[str], error_type: str
) -> None:
    (error,) = _refusals(client, "GET", path)

    assert (error["loc"], error["type"]) == (loc, error_type)


@pytest.mark.parametrize("path", ["/search?q=%20kettle", "/search?q=x&top_k=1000"])
def test_a_query_parameter_in_range_is_answered(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


def test_the_largest_page_is_answered(client: TestClient) -> None:
    assert client.get("/memory/fake?limit=1000").status_code == 200


def test_a_configured_top_k_out_of_range_is_500_not_422() -> None:
    base = get_settings(Environment.TESTING)
    # model_copy skips validation, so it builds what loading settings refuses.
    search = base.search.model_copy(update={"top_k": 0})
    app = create_app(open_fake_kb(settings=base.model_copy(update={"search": search})))

    assert TestClient(app, raise_server_exceptions=False).get("/search?q=x").status_code == 500
    with pytest.raises(ValidationError, match="top_k"):
        TestClient(app).get("/search?q=x")


@pytest.mark.parametrize("path", [f"/memory/fake/{_ABSENT}", "/memory/fake", "/search?q=drift"])
def test_a_stored_payload_its_kind_refuses_is_500_not_422(kb: KnowledgeBase, path: str) -> None:
    kb.store.upsert(
        [
            Point(
                id=_ABSENT,
                kind="fake",
                updated_at=datetime.now(UTC),
                payload={"title": "drift", "colour": "red"},
                vector=kb.embedder.embed_query("drift"),
            )
        ]
    )
    client = TestClient(create_app(kb), raise_server_exceptions=False)

    assert client.get(path).status_code == 500
    with pytest.raises(StoredItemInvalid, match=str(_ABSENT)):
        TestClient(create_app(kb)).get(path)


def _corrupt_envelope_kb(tmp_path: Path) -> KnowledgeBase:
    """A LanceDB knowledge base holding item ``_ABSENT`` with a payload that is not an object."""
    kb = open_fake_kb(settings=lancedb_settings(tmp_path))
    kb.store.upsert(
        [
            Point(
                id=_ABSENT,
                kind="fake",
                updated_at=datetime.now(UTC),
                payload={"title": "drift", "tags": []},
                vector=kb.embedder.embed_query("drift"),
            )
        ]
    )
    db = lancedb.connect(tmp_path)
    (table,) = db.list_tables().tables
    # update's `values` is an unparameterised dict in lancedb's annotations.
    _ = db.open_table(table).update(  # pyright: ignore[reportUnknownMemberType]
        values={"payload": "[]"}
    )
    return kb


@pytest.mark.parametrize("path", [f"/memory/fake/{_ABSENT}", "/memory/fake", "/search?q=drift"])
def test_a_stored_envelope_the_store_refuses_is_500_not_422(tmp_path: Path, path: str) -> None:
    kb = _corrupt_envelope_kb(tmp_path)
    client = TestClient(create_app(kb), raise_server_exceptions=False)

    assert client.get(path).status_code == 500
    with pytest.raises(StoredItemInvalid, match=f"row {_ABSENT} .*not a valid"):
        TestClient(create_app(kb)).get(path)


def test_an_item_with_a_corrupt_envelope_can_be_deleted(tmp_path: Path) -> None:
    client = TestClient(create_app(_corrupt_envelope_kb(tmp_path)))

    assert client.delete(f"/memory/fake/{_ABSENT}").status_code == 202
    assert client.get(f"/memory/fake/{_ABSENT}").status_code == 404
