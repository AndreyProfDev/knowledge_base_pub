"""An in-memory FIFO of writes, worked by one background thread of this process."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from tools_knowledge_base.errors import UnknownRequest

type RequestOutcome = tuple[Literal["failed"], str] | tuple[Literal["queued", "done"], None]

THREAD_NAME = "kb-write-queue"


class WriteQueue:
    """Queue jobs and answer for their request ids; a job lost at process exit is accepted.

    One worker thread, started by the first ``submit`` (never earlier), runs jobs in submit
    order, so two writes to one item land in that order. ``drain`` runs the rest in the
    caller's thread. ``background=False`` never starts the thread: tests and the CLI drain.
    """

    def __init__(self, *, background: bool = True) -> None:
        self._background = background
        self._lock = threading.Lock()
        self._wakeup = threading.Condition(self._lock)
        self._running = threading.Lock()  # held across "pop one job and run it"
        self._jobs: deque[tuple[str, Callable[[], object]]] = deque()
        self._states: dict[str, RequestOutcome] = {}
        self._thread: threading.Thread | None = None

    def submit(self, job: Callable[[], object]) -> str:
        """Queue ``job`` and return its request id at once."""
        request_id = str(uuid4())
        with self._wakeup:
            self._states[request_id] = ("queued", None)
            self._jobs.append((request_id, job))
            if self._background and self._thread is None:
                self._thread = threading.Thread(target=self._work, name=THREAD_NAME, daemon=True)
                self._thread.start()
            self._wakeup.notify()
        return request_id

    def settled(self, error: str | None = None) -> str:
        """Record a request that already ran: ``done``, or ``failed`` with ``error``."""
        request_id = str(uuid4())
        with self._lock:
            self._states[request_id] = ("done", None) if error is None else ("failed", error)
        return request_id

    def status(self, request_id: str) -> RequestOutcome:
        """The request's state and, when failed, its error message.

        Raises:
            UnknownRequest: this process never issued ``request_id``.
        """
        with self._lock:
            state = self._states.get(request_id)
        if state is None:
            msg = (
                f"request {request_id} was not issued by this server process "
                "(it restarted, or the id came from another conversation)"
            )
            raise UnknownRequest(msg)
        return state

    def drain(self) -> None:
        """Run everything queued in this thread; wait for a job the worker has in flight."""
        while self._run_next():
            pass

    def queued(self) -> int:
        """How many requests are queued or running."""
        with self._lock:
            return sum(1 for kind, _ in self._states.values() if kind == "queued")

    def _run_next(self) -> bool:
        with self._running:
            with self._lock:
                if not self._jobs:
                    return False  # pragma: no mutate, True spins drain forever
                request_id, job = self._jobs.popleft()
            outcome: RequestOutcome = ("done", None)
            try:
                job()
            except Exception as exc:
                outcome = ("failed", f"{type(exc).__name__}: {exc}")
            with self._lock:
                self._states[request_id] = outcome
            return True

    def _work(self) -> None:
        while True:
            with self._wakeup:
                self._wakeup.wait_for(lambda: bool(self._jobs))
            self._run_next()
