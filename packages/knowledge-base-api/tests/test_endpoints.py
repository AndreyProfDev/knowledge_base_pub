from __future__ import annotations

from fake_kb import stored
from fastapi.testclient import TestClient

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.queue import drain


def test_get_round_trips_the_payload(client: TestClient, kb: KnowledgeBase) -> None:
    accepted = stored(kb, "kettle", ["kitchen", "tea"])

    response = client.get(f"/memory/fake/{accepted.item_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(accepted.item_id)
    assert body["kind"] == "fake"
    assert body["payload"] == {"title": "kettle", "tags": ["kitchen", "tea"]}


def test_list_pages_through_every_item(client: TestClient, kb: KnowledgeBase) -> None:
    ids = {str(stored(kb, title).item_id) for title in ("alpha", "beta", "gamma")}

    first = client.get("/memory/fake", params={"limit": 2}).json()
    rest = client.get("/memory/fake", params={"limit": 2, "cursor": first["next_cursor"]}).json()

    assert len(first["items"]) == 2
    assert rest["next_cursor"] is None
    assert {item["id"] for item in first["items"] + rest["items"]} == ids


def test_delete_answers_202_the_item_is_gone_and_its_request_is_pollable(
    client: TestClient, kb: KnowledgeBase
) -> None:
    accepted = stored(kb, "kettle")

    deleted = client.delete(f"/memory/fake/{accepted.item_id}")

    assert deleted.status_code == 202
    body = deleted.json()
    assert body["item_id"] == str(accepted.item_id)
    assert deleted.headers["Location"] == f"/requests/{body['request_id']}"
    assert client.get(f"/memory/fake/{accepted.item_id}").status_code == 404
    drain(kb.huey)
    assert client.get(deleted.headers["Location"]).json()["status"] == "done"


def test_search_returns_the_hit(client: TestClient, kb: KnowledgeBase) -> None:
    accepted = stored(kb, "kettle", ["kitchen"])
    stored(kb, "bicycle", ["garage"])

    hits = client.get("/search", params={"q": "kettle kitchen", "kind": "fake", "top_k": 1}).json()

    assert [hit["id"] for hit in hits] == [str(accepted.item_id)]
    assert hits[0]["payload"]["title"] == "kettle"
    assert isinstance(hits[0]["score"], float)


def test_search_applies_min_score(client: TestClient, kb: KnowledgeBase) -> None:
    stored(kb, "kettle")

    assert client.get("/search", params={"q": "kettle"}).json()
    assert client.get("/search", params={"q": "kettle", "min_score": 1.5}).json() == []


def test_requests_reports_a_finished_write(client: TestClient, kb: KnowledgeBase) -> None:
    accepted = stored(kb, "kettle")

    assert client.get(f"/requests/{accepted.request_id}").json() == {
        "request_id": accepted.request_id,
        "status": "done",
        "error": None,
    }


def test_kinds_lists_each_kind_with_its_schema(client: TestClient) -> None:
    (kind,) = client.get("/kinds").json()

    assert kind["name"] == "fake"
    assert set(kind["payload_schema"]["properties"]) == {"title", "tags"}
    assert kind["max_chars"] == 500


def test_an_over_cap_store_is_a_422_with_count_cap_and_hint(
    client: TestClient, kb: KnowledgeBase
) -> None:
    response = client.post("/memory/fake", json={"title": "t", "tags": ["x" * 499]})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == (
        "fake item is 501 characters; the fake limit is 500 (counted over title and tags). "
        "Split the tags across several fake items."
    )
    assert kb.huey.pending_count() == 0


def test_a_foreign_host_header_gets_400(client: TestClient) -> None:
    response = client.get("/kinds", headers={"Host": "evil.example"})

    assert response.status_code == 400


def test_an_allowed_host_with_a_port_is_served(client: TestClient) -> None:
    assert client.get("/kinds", headers={"Host": "localhost:8000"}).status_code == 200
