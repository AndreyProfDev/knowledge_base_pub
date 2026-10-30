"""Repository-wide mccabe report, as GitHub-flavoured Markdown on stdout.

Scores come from the same ruff rule `make complexity` gates on, with the limit
forced to 0 so every function is reported instead of only the violations.

This does not judge: a function over the limit is printed, not an error. It
does raise if ruff fails or its output is unrecognisable — a partial count
would read as a clean repository. CI marks the reporting step
`continue-on-error` so that raise cannot block the gate itself.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUCKETS = ((1, 3), (4, 6), (7, 10))
TOP_N = 15
MESSAGE = re.compile(r"`(?P<name>[^`]+)` is too complex \((?P<score>\d+) > \d+\)")


@dataclass(frozen=True)
class Function:
    """One measured function."""

    score: int
    name: str
    path: str
    line: int


def limit() -> int:
    """Read the enforced max-complexity from pyproject.toml."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    mccabe = config["tool"]["ruff"]["lint"]["mccabe"]
    return int(mccabe["max-complexity"])


def scan() -> list[Function]:
    """Measure every function in the workspace."""
    result = subprocess.run(
        [
            shutil.which("ruff") or "ruff",
            "check",
            "--select=C901",
            "--config=lint.mccabe.max-complexity=0",
            "--output-format=json",
            ".",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 0 is nothing found, 1 is violations found — anything else is ruff failing.
    if result.returncode > 1:
        msg = f"ruff exited {result.returncode}: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return sorted(
        map(_parse, json.loads(result.stdout)),
        key=lambda fn: (-fn.score, fn.path, fn.line),
    )


def _parse(violation: dict[str, object]) -> Function:
    """Turn one ruff violation into a Function."""
    message = str(violation["message"])
    matched = MESSAGE.fullmatch(message)
    if not matched:
        # Only C901 is selected, so every message should match. One that does
        # not means ruff changed its wording: report nothing rather than a
        # quietly incomplete count.
        msg = f"unrecognised C901 message: {message!r}"
        raise ValueError(msg)
    path = Path(str(violation["filename"]))
    location = violation["location"]
    if not isinstance(location, dict):
        msg = f"unrecognised C901 location: {location!r}"
        raise TypeError(msg)
    return Function(
        score=int(matched["score"]),
        name=matched["name"],
        path=str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
        line=int(location["row"]),
    )


def _table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    """Render a Markdown table."""
    return [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]


def _rows(functions: list[Function]) -> list[tuple[str, ...]]:
    """Render functions as `score | name | location` rows."""
    return [(str(fn.score), f"`{fn.name}`", f"`{fn.path}:{fn.line}`") for fn in functions]


def _distribution(functions: list[Function], maximum: int) -> list[str]:
    """Render the bucketed score distribution."""
    rows = [
        (f"{low}-{high}", str(sum(low <= fn.score <= high for fn in functions)))
        for low, high in BUCKETS
    ]
    over = sum(fn.score > maximum for fn in functions)
    return _table(("complexity", "functions"), [*rows, (f"> {maximum}", str(over))])


def render(functions: list[Function], maximum: int) -> str:
    """Build the whole report."""
    if not functions:
        return "## Complexity\n\nNo functions measured.\n"
    over = [fn for fn in functions if fn.score > maximum]
    lines = [
        "## Complexity",
        "",
        f"**{len(functions)}** functions · highest **{functions[0].score}** · "
        f"limit **{maximum}** · over limit **{len(over)}**",
        "",
        *_distribution(functions, maximum),
        "",
    ]
    if over:
        lines += ["### Over the limit", "", *_table(_HEAD, _rows(over)), ""]
    else:
        lines += [f"Every function is at or under {maximum}.", ""]
    lines += [
        f"<details><summary>Top {TOP_N} most complex</summary>",
        "",
        *_table(_HEAD, _rows(functions[:TOP_N])),
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)


_HEAD = ("complexity", "function", "location")


def main() -> int:
    """Print the report."""
    print(render(scan(), limit()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
