"""The committed ``openapi.json`` is what the web UI's client is generated from."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

from fake_kb import open_fake_kb

from tools_knowledge_base_api.app import create_app

_SNAPSHOT = Path(__file__).resolve().parents[1] / "openapi.json"
_REGENERATE = "make kb-openapi"


def test_every_operation_id_is_the_operation_it_binds() -> None:
    """The generated client's method names; FastAPI's derived ones embed the path."""
    paths = create_app(open_fake_kb()).openapi()["paths"]
    ids = {operation["operationId"] for path in paths.values() for operation in path.values()}

    assert ids == {
        "store_memory",
        "update_memory_item",
        "get_memory_item",
        "list_memory_items",
        "delete_memory_item",
        "search_memory",
        "get_memory_request",
        "list_memory_kinds",
        "warmup_memory",
        "get_warmup_progress",
    }


def test_every_summary_names_its_operation() -> None:
    """Not FastAPI's default, the title-cased inner function name ("Get", "Request")."""
    paths = create_app(open_fake_kb()).openapi()["paths"]
    operations = [operation for path in paths.values() for operation in path.values()]

    assert all(
        op["summary"] == op["operationId"].replace("_", " ").capitalize() for op in operations
    )


def test_the_schema_version_is_the_package_version() -> None:
    info = create_app(open_fake_kb()).openapi()["info"]

    assert info["version"] == version("tools-knowledge-base-api")


def test_post_and_put_declare_the_location_header_on_202() -> None:
    paths = create_app(open_fake_kb()).openapi()["paths"]
    writes = [paths["/memory/{kind}"]["post"], paths["/memory/{kind}/{item_id}"]["put"]]

    assert all("Location" in write["responses"]["202"]["headers"] for write in writes)


def test_both_warmup_operations_declare_their_404() -> None:
    paths = create_app(open_fake_kb()).openapi()["paths"]
    operations = [paths["/warmup"]["post"], paths["/warmup/{run_id}"]["get"]]

    assert all(
        "detail" in op["responses"]["404"]["content"]["application/json"]["schema"]["properties"]
        for op in operations
    )


def test_the_committed_schema_matches_the_app() -> None:
    committed = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))

    assert committed == create_app(open_fake_kb()).openapi(), (
        f"{_SNAPSHOT.name} drifted from app.openapi(); regenerate it: {_REGENERATE}"
    )
