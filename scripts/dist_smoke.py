"""Prove a ``make dist`` directory runs through ``uvx`` with no clone.

Usage: ``uv run python scripts/dist_smoke.py <dist dir>``. Needs ``uv`` and PyPI.

Every run is isolated: cwd, ``UV_CACHE_DIR`` and ``KB_DATA_DIR`` are temp dirs
(removed on exit), and ``VIRTUAL_ENV``, ``OPEN_AI_API_KEY``, ``MCP_TRANSPORT``
and ``TOOLS_ENV`` are removed from the environment. The first failing check
prints its name and the server's stderr and exits 1. The uvx runner lives in
``dist_smoke_runner.py``.
"""

import configparser
import json
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, NoReturn

from dist_smoke_runner import LAST_ID, Runner, SmokeError

FAIL_FAST_S = 10
FAKE_KEY = "sk-smoke-not-real"
WHEEL_COUNT = 9
KINDS = {"entity", "knowledge", "workflow"}
STORES = {"sqlite", "qdrant", "lancedb"}
GROUPS = {
    "tools_knowledge_base.memory_kinds": KINDS,
    "tools_knowledge_base.vector_stores": STORES,
}
YAMLS = {
    "tools_knowledge_base-": (
        "tools_knowledge_base/configs/base/knowledge_base.yaml",
        "tools_knowledge_base/configs/local/knowledge_base.yaml",
    ),
    "knowledge_base_mcp_server-": ("knowledge_base_mcp_server/configs/base/mcp_server.yaml",),
}
TOOLS = {
    f"{verb}_{kind}" for verb in ("delete", "get", "list", "store", "update") for kind in KINDS
} | {"get_memory_request", "search_memory"}
INSTALLED = "installed: ['entity', 'knowledge', 'workflow']"
SERVER = ["--from", "knowledge-base-mcp-server", "knowledge-base-mcp"]


def _fail(what: str, proc: subprocess.CompletedProcess[str]) -> NoReturn:
    msg = f"{what} (exit {proc.returncode})\n{proc.stderr}"
    raise SmokeError(msg)


def check_shape(dist: Path) -> None:
    """The dir holds exactly the 9 wheels and constraints.txt, with YAMLs and entry points."""
    names = sorted(p.name for p in dist.iterdir() if p.is_file() and p.name != ".gitignore")
    wheels = [n for n in names if n.endswith(".whl")]
    if len(wheels) != WHEEL_COUNT or set(names) - set(wheels) != {"constraints.txt"}:
        msg = f"expected {WHEEL_COUNT} wheels + constraints.txt, found {names}"
        raise SmokeError(msg)
    found: dict[str, set[str]] = {group: set() for group in GROUPS}
    for wheel in wheels:
        with zipfile.ZipFile(dist / wheel) as zf:
            members = set(zf.namelist())
            for prefix, paths in YAMLS.items():
                missing = [p for p in paths if wheel.startswith(prefix) and p not in members]
                if missing:
                    msg = f"{wheel} lacks {missing}"
                    raise SmokeError(msg)
            for member in members:
                if member.endswith(".dist-info/entry_points.txt"):
                    _collect_entry_points(zf.read(member).decode(), found)
    for group, expected in GROUPS.items():
        if found[group] != expected:
            msg = f"entry points {group}: {sorted(found[group])}, expected {sorted(expected)}"
            raise SmokeError(msg)


def _collect_entry_points(text: str, found: dict[str, set[str]]) -> None:
    parser = configparser.ConfigParser()
    parser.read_string(text)
    for group in GROUPS:
        if parser.has_section(group):
            found[group].update(parser.options(group))


def _parse_replies(proc: subprocess.CompletedProcess[str]) -> dict[object, Any]:
    replies: dict[object, Any] = {}
    for line in proc.stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            _fail(f"stdout line is not JSON: {line!r}", proc)
        if isinstance(message, dict):
            replies[message.get("id")] = message
    return replies


def check_handshake(runner: Runner) -> None:
    """With MCP_TRANSPORT unset the server answers on stdio and lists the 17 tools."""
    proc = runner.converse(SERVER, key=FAKE_KEY, data_dir=runner.data_dir())
    if proc.returncode != 0:
        _fail("server did not exit 0 on EOF", proc)
    replies = _parse_replies(proc)
    name = replies.get(1, {}).get("result", {}).get("serverInfo", {}).get("name")
    if name != "knowledge_base":
        _fail(f"serverInfo.name is {name!r}", proc)
    listed = replies.get(LAST_ID, {}).get("result", {}).get("tools", [])
    tools = {t["name"] for t in listed}
    if tools != TOOLS:
        _fail(f"tools differ: missing {sorted(TOOLS - tools)}, extra {sorted(tools - TOOLS)}", proc)


def check_fail_fast(runner: Runner) -> None:
    """Without a key the server refuses to start and names OPEN_AI_API_KEY and the .env path."""
    data_dir = runner.data_dir()
    started = time.monotonic()
    proc = runner.converse(SERVER, key=None, data_dir=data_dir)
    elapsed = time.monotonic() - started
    if proc.returncode == 0:
        _fail("server started without a key", proc)
    if elapsed > FAIL_FAST_S:
        _fail(f"refusal took {elapsed:.1f}s, over {FAIL_FAST_S}s", proc)
    for needle in ("OPEN_AI_API_KEY", str(data_dir / ".env")):
        if needle not in proc.stderr:
            _fail(f"stderr lacks {needle!r}", proc)
    if proc.stdout:
        _fail(f"stdout is not empty: {proc.stdout!r}", proc)


def check_warmup(runner: Runner) -> None:
    """The uvx warm-up (README form) sees all 3 kinds and rejects an unknown one pre-embedding."""
    data_dir = runner.data_dir()
    warmup = data_dir / "warmup"
    warmup.mkdir()
    (warmup / "smoke-gadget.yaml").write_text("gadget:\n- name: x\n")
    form_b = ["--with", "knowledge-base-mcp-server", "--from", "tools-knowledge-base"]
    proc = runner.run([*form_b, "knowledge-base-cli", "warmup"], key=FAKE_KEY, data_dir=data_dir)
    if proc.returncode != 1 or INSTALLED not in proc.stderr:
        _fail(f"warm-up did not exit 1 with {INSTALLED!r}", proc)


def main(argv: list[str]) -> int:
    """Run checks 1-4 against ``argv[0]``; return the exit code."""
    if len(argv) != 1:
        print("usage: dist_smoke.py <dist dir>", file=sys.stderr)
        return 2
    dist = Path(argv[0]).resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="dist-smoke-") as root:
            check_shape(dist)
            print("ok: check_shape")
            runner = Runner(dist, Path(root))
            for check in (check_handshake, check_fail_fast, check_warmup):
                check(runner)
                print(f"ok: {check.__name__}")
    except (SmokeError, OSError) as exc:
        print(f"dist-smoke FAILED: {exc}", file=sys.stderr)
        return 1
    print("dist-smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
