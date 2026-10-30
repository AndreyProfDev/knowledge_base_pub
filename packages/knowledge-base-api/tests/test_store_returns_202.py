"""Store and edit answer before the worker runs: the async contract, not faked."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.queue import drain


def _status(client: TestClient, location: str) -> str:
    return client.get(location).json()["status"]


def test_post_answers_202_and_points_at_the_request(client: TestClient, kb: KnowledgeBase) -> None:
    response = client.post("/memory/fake", json={"title": "kettle", "tags": []})

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "queued"
    location = response.headers["Location"]
    assert location == f"/requests/{accepted['request_id']}"
    assert _status(client, location) == "queued"
    assert client.get(f"/memory/fake/{accepted['item_id']}").status_code == 404

    drain(kb.huey)

    assert _status(client, location) == "done"
    assert client.get(f"/memory/fake/{accepted['item_id']}").status_code == 200


def test_put_answers_202_and_replaces_the_item(client: TestClient, kb: KnowledgeBase) -> None:
    old = client.post("/memory/fake", json={"title": "kettle", "tags": []}).json()
    drain(kb.huey)

    response = client.put(f"/memory/fake/{old['item_id']}", json={"title": "teapot", "tags": []})

    assert response.status_code == 202
    new = response.json()
    location = response.headers["Location"]
    assert location == f"/requests/{new['request_id']}"
    assert _status(client, location) == "queued"

    drain(kb.huey)

    assert _status(client, location) == "done"
    assert new["item_id"] != old["item_id"]
    assert client.get(f"/memory/fake/{old['item_id']}").status_code == 404
    item = client.get(f"/memory/fake/{new['item_id']}").json()
    assert item["payload"]["title"] == "teapot"
