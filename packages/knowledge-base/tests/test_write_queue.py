"""The in-memory write queue: FIFO, statuses, and its one lazily started daemon thread."""

from __future__ import annotations

import threading

import pytest

from tools_knowledge_base.errors import UnknownRequest
from tools_knowledge_base.write_queue import THREAD_NAME, WriteQueue

WAIT = 5.0


def _threads() -> int:
    return sum(1 for thread in threading.enumerate() if thread.name == THREAD_NAME)


def _boom() -> None:
    msg = "no luck"
    raise RuntimeError(msg)


def test_a_submitted_job_is_queued_until_drained() -> None:
    writes = WriteQueue(background=False)
    ran: list[str] = []

    request_id = writes.submit(lambda: ran.append("a"))

    assert (writes.status(request_id), ran, writes.queued()) == (("queued", None), [], 1)
    writes.drain()
    assert (writes.status(request_id), ran, writes.queued()) == (("done", None), ["a"], 0)


def test_the_wakeup_condition_shares_the_state_lock() -> None:
    writes = WriteQueue(background=False)

    with writes._wakeup:
        assert writes._lock.locked()


def test_draining_an_empty_queue_returns() -> None:
    writes = WriteQueue(background=False)
    worker = threading.Thread(target=writes.drain, daemon=True)

    worker.start()
    worker.join(WAIT)

    assert not worker.is_alive()


def test_drain_runs_jobs_in_submit_order() -> None:
    writes = WriteQueue(background=False)
    ran: list[int] = []
    for n in range(3):
        writes.submit(lambda n=n: ran.append(n))

    writes.drain()

    assert ran == [0, 1, 2]


def test_a_raising_job_fails_with_its_message_and_does_not_stop_the_rest() -> None:
    writes = WriteQueue(background=False)
    ran: list[str] = []
    bad = writes.submit(_boom)
    good = writes.submit(lambda: ran.append("later"))

    writes.drain()

    assert writes.status(bad) == ("failed", "RuntimeError: no luck")
    assert (writes.status(good), ran) == (("done", None), ["later"])


def test_an_unknown_request_id_is_refused_with_the_restart_hint() -> None:
    with pytest.raises(UnknownRequest) as caught:
        WriteQueue(background=False).status("abc")

    assert str(caught.value) == (
        "request abc was not issued by this server process "
        "(it restarted, or the id came from another conversation)"
    )


def test_settled_records_a_finished_or_failed_request() -> None:
    writes = WriteQueue(background=False)

    done = writes.settled()
    failed = writes.settled("disk full")

    assert (writes.status(done), writes.status(failed)) == (("done", None), ("failed", "disk full"))
    assert (done != failed, writes.queued()) == (True, 0)


def test_a_foreground_queue_never_starts_a_thread() -> None:
    before = _threads()

    WriteQueue(background=False).submit(lambda: None)

    assert _threads() == before


def test_the_background_thread_starts_on_the_first_submit_only() -> None:
    before = _threads()
    writes = WriteQueue()
    assert _threads() == before

    writes.submit(lambda: None)
    writes.submit(lambda: None)
    writes.drain()

    assert _threads() == before + 1
    assert all(t.daemon for t in threading.enumerate() if t.name == THREAD_NAME)


def test_the_background_thread_runs_jobs_in_submit_order() -> None:
    writes = WriteQueue()
    gate = threading.Event()
    ran: list[str] = []
    writes.submit(gate.wait)
    first = writes.submit(lambda: ran.append("first"))
    second = writes.submit(lambda: ran.append("second"))
    assert writes.queued() == 3

    gate.set()
    writes.drain()

    assert ran == ["first", "second"]
    assert (writes.status(first), writes.status(second)) == (("done", None), ("done", None))


def test_drain_waits_for_the_job_the_worker_has_in_flight() -> None:
    writes = WriteQueue()
    started = threading.Event()
    release = threading.Event()

    def slow() -> None:
        started.set()
        release.wait(WAIT)

    request_id = writes.submit(slow)
    assert started.wait(WAIT)
    drainer = threading.Thread(target=writes.drain)
    drainer.start()
    drainer.join(0.2)
    assert drainer.is_alive()
    assert writes.status(request_id) == ("queued", None)

    release.set()
    drainer.join(WAIT)

    assert not drainer.is_alive()
    assert writes.status(request_id) == ("done", None)
