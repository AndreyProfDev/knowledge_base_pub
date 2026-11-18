"""Dump writers racing on one item's file: each writes its own temp file, so none loses it."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from tools_knowledge_base.errors import WarmupDumpFailed
from tools_knowledge_base.warmup_dump import _temp_path, write_dump

# An inline script, not a spawned test function: the child needs no test-module import path
# (which a mutmut sandbox lacks). Any ``FileNotFoundError`` makes it exit non-zero.
HAMMER = """
import sys
from pathlib import Path
from uuid import UUID

from tools_knowledge_base.warmup_dump import write_dump

root, item_id, title = Path(sys.argv[1]), UUID(sys.argv[2]), sys.argv[3]
for _ in range(200):
    write_dump(root, "fake", item_id, {"title": title, "tags": []})
"""


def test_the_temp_name_is_unique_per_process_and_thread(tmp_path: Path) -> None:
    assert _temp_path(tmp_path, "fake-1.yaml") == tmp_path / (
        f".fake-1.yaml.{os.getpid()}.{threading.get_ident()}.tmp"
    )


def test_two_threads_use_different_temp_names(tmp_path: Path) -> None:
    names: list[Path] = []
    thread = threading.Thread(target=lambda: names.append(_temp_path(tmp_path, "x.yaml")))
    thread.start()
    thread.join()

    assert names != [_temp_path(tmp_path, "x.yaml")]


def test_two_processes_writing_one_item_200_times_both_succeed(tmp_path: Path) -> None:
    item_id = uuid4()
    children = [
        subprocess.Popen([sys.executable, "-c", HAMMER, str(tmp_path), str(item_id), t])
        for t in ("one", "two")
    ]
    for child in children:
        child.wait(timeout=120)

    assert [child.returncode for child in children] == [0, 0]
    loaded = yaml.safe_load((tmp_path / f"fake-{item_id}.yaml").read_text())
    assert loaded["fake"][0]["title"] in {"one", "two"}
    assert [p.name for p in tmp_path.iterdir()] == [f"fake-{item_id}.yaml"]


def test_a_failed_replace_leaves_the_temp_file_under_its_unique_name(tmp_path: Path) -> None:
    item_id = uuid4()
    name = f"fake-{item_id}.yaml"
    (tmp_path / name).mkdir()  # replacing a directory with a file fails

    with pytest.raises(WarmupDumpFailed):
        write_dump(tmp_path, "fake", item_id, {"title": "a", "tags": []})

    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [name, _temp_path(tmp_path, name).name]
    )


def test_a_single_write_leaves_only_the_dump_file(tmp_path: Path) -> None:
    item_id = uuid4()

    write_dump(tmp_path, "fake", item_id, {"title": "a", "tags": []})

    assert [p.name for p in tmp_path.iterdir()] == [f"fake-{item_id}.yaml"]
