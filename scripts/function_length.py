"""Fail on any function over `--max-lines`, printed as `path:lineno: name (N lines)`.

Measures a function's *own* span: its full source range minus the ranges of
any directly nested function or class. Without that subtraction, a factory
whose body is a handful of nested functions — e.g. `def tools(client):
def create_issue(...): ...` — would be judged on the sum of everything it
contains instead of its own few lines; each nested function is measured (and
gated) independently as its own entry, exactly like a top-level one.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Function:
    """One measured function."""

    lines: int
    name: str
    path: str
    lineno: int


def source_files() -> list[Path]:
    """Every tracked Python file in the workspace."""
    return sorted(
        p
        for p in ROOT.glob("packages/**/*.py")
        if not {".venv", "node_modules", "mutants"} & set(p.parts)
    )


def own_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """The function's line span, minus any directly nested def/class."""
    total = (node.end_lineno or node.lineno) - node.lineno + 1
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            total -= (child.end_lineno or child.lineno) - child.lineno + 1
    return total


def scan() -> list[Function]:
    """Measure every function in the workspace, longest first."""
    functions: list[Function] = []
    for path in source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = str(path.relative_to(ROOT))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                functions.append(Function(own_lines(node), node.name, rel, node.lineno))
    return sorted(functions, key=lambda fn: (-fn.lines, fn.path, fn.lineno))


def main() -> int:
    """Print each violation and return 1, or return 0 if there are none."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-lines", type=int, required=True)
    args = parser.parse_args()

    over = [fn for fn in scan() if fn.lines > args.max_lines]
    if not over:
        return 0
    print(f"functions over {args.max_lines} lines:")
    for fn in over:
        print(f"{fn.path}:{fn.lineno}: {fn.name} ({fn.lines} lines)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
