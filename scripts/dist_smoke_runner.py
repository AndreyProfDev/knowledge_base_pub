"""The uvx runner behind ``dist_smoke.py``: isolated env, temp dirs, an MCP client exchange."""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
from pathlib import Path

TIMEOUT_S = 120
INIT = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "smoke", "version": "0"},
}
LAST_ID = 2
REQUESTS = "".join(
    json.dumps(message) + "\n"
    for message in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": LAST_ID, "method": "tools/list"},
    )
)


class SmokeError(Exception):
    """A check failed; the message names what, and carries stderr when there is some."""


class Runner:
    """Runs uvx outside the repo, with one shared temp uv cache; all temp dirs live in ``root``."""

    def __init__(self, dist: Path, root: Path) -> None:
        """Resolve uvx and make the cwd and uv cache dirs under ``root``."""
        uvx = shutil.which("uvx")
        if uvx is None:
            msg = "uvx is not on PATH"
            raise SmokeError(msg)
        self.root = root
        self.cwd = tempfile.mkdtemp(prefix="cwd-", dir=root)
        self.cache = tempfile.mkdtemp(prefix="uv-", dir=root)
        self.prefix = [
            uvx,
            "--python",
            "3.12",
            "-c",
            str(dist / "constraints.txt"),
            "--find-links",
            str(dist),
        ]

    def data_dir(self) -> Path:
        """A fresh, empty ``KB_DATA_DIR``."""
        return Path(tempfile.mkdtemp(prefix="data-", dir=self.root))

    def _env(self, key: str | None, data_dir: Path) -> dict[str, str]:
        skip = {"VIRTUAL_ENV", "OPEN_AI_API_KEY", "MCP_TRANSPORT", "TOOLS_ENV"}
        env = {k: v for k, v in os.environ.items() if k not in skip}
        env.update(UV_CACHE_DIR=self.cache, KB_DATA_DIR=str(data_dir))
        if key is not None:
            env["OPEN_AI_API_KEY"] = key
        return env

    def run(
        self, args: list[str], *, key: str | None, data_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        """Run ``uvx <prefix> <args>`` with a fresh env, the key (or none) and the data dir."""
        try:
            return subprocess.run(
                [*self.prefix, *args],
                input="",
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
                cwd=self.cwd,
                env=self._env(key, data_dir),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"timed out after {TIMEOUT_S}s: {' '.join(args)}"
            raise SmokeError(msg) from exc

    def converse(
        self, args: list[str], *, key: str | None, data_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        """Act as an MCP client: send ``REQUESTS``, close stdin once reply ``LAST_ID`` is in.

        Closing stdin straight after the requests (a pipe or ``< file``) races the
        server: the SDK ends the session on EOF and can drop a reply still being
        built. A real client keeps stdin open until it has its answer.
        """
        with (self.root / "stderr.log").open("w+") as err:
            proc = subprocess.Popen(
                [*self.prefix, *args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=err,
                text=True,
                cwd=self.cwd,
                env=self._env(key, data_dir),
                start_new_session=True,
            )
            timed_out = threading.Event()

            def kill() -> None:
                timed_out.set()
                _kill_group(proc)

            timer = threading.Timer(TIMEOUT_S, kill)
            timer.start()
            try:
                stdout = _exchange(proc)
                code = proc.wait()
            finally:
                timer.cancel()
                _kill_group(proc)
                proc.wait()
            err.seek(0)
            stderr = err.read()
        if timed_out.is_set():
            msg = f"timed out after {TIMEOUT_S}s: {' '.join(args)}\n{stderr}"
            raise SmokeError(msg)
        return subprocess.CompletedProcess(proc.args, code, stdout, stderr)


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """Kill uvx and the server it spawned: a surviving child holds stdout open, so reads hang."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


def _exchange(proc: subprocess.Popen[str]) -> str:
    """Write the requests, read stdout until reply ``LAST_ID`` (or EOF), close stdin, drain."""
    assert proc.stdin is not None  # noqa: S101
    assert proc.stdout is not None  # noqa: S101
    with contextlib.suppress(BrokenPipeError):  # the server exited first: exit code says why
        proc.stdin.write(REQUESTS)
        proc.stdin.flush()
    lines: list[str] = []
    for line in proc.stdout:
        lines.append(line)
        if _reply_id(line) == LAST_ID:
            break
    with contextlib.suppress(BrokenPipeError):
        proc.stdin.close()
    lines.extend(proc.stdout)
    proc.stdout.close()
    return "".join(lines)


def _reply_id(line: str) -> object:
    try:
        message = json.loads(line)
    except ValueError:
        return None
    return message.get("id") if isinstance(message, dict) else None
