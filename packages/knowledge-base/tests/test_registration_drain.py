"""``register``'s drain: the queued writes run, bounded, on a daemon thread."""

from __future__ import annotations

import threading

from fake_kb import open_fake_kb
from fake_server import keyed_settings
from mcp.server import MCPServer

from tools_knowledge_base.operations import store_memory
from tools_knowledge_base.registration import register

WAIT = 5.0


def test_drain_runs_the_queued_writes_and_returns_how_many_are_left() -> None:
    kb = open_fake_kb()
    registered = register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _s: kb)
    accepted = store_memory(kb, "fake", {"title": "one", "tags": []})

    assert registered.queued() == 1
    assert registered.drain(WAIT) == 0
    assert registered.queued() == 0
    assert [item.id for item in kb.store.get([accepted.item_id])] == [accepted.item_id]


def test_drain_gives_up_on_a_stuck_write_and_leaves_a_daemon_thread() -> None:
    kb = open_fake_kb()
    registered = register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _s: kb)
    release = threading.Event()
    kb.writes.submit(lambda: release.wait(WAIT))

    left = registered.drain(0.05)
    workers = [t for t in threading.enumerate() if t.name == "kb-exit-drain"]
    release.set()
    for worker in workers:
        worker.join(WAIT)

    assert left == 1
    assert [w.daemon for w in workers] == [True]
    assert registered.queued() == 0
