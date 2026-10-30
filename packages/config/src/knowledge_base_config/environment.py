"""Environment enum used by the loader to select per-package YAML overrides."""

from __future__ import annotations

import os
from enum import StrEnum

TOOLS_ENV_VAR = "TOOLS_ENV"


class Environment(StrEnum):
    """Deployment environment. The value is the YAML overlay directory name."""

    LOCAL = "local"
    TESTING = "testing"
    PROD = "prod"


def environment_from_env() -> Environment:
    """Return the environment named by ``TOOLS_ENV``, defaulting to ``local``.

    Lives here rather than in each package because this is the one module
    allowed to read ``os.environ``, and every frontend that cannot take a
    ``--env`` flag — MCP servers, the notebook facade — needs it.
    """
    raw = os.environ.get(TOOLS_ENV_VAR, "").strip().lower()
    if not raw:
        return Environment.LOCAL
    try:
        return Environment(raw)
    except ValueError:
        valid = ", ".join(e.value for e in Environment)
        msg = f"{TOOLS_ENV_VAR}={raw!r} is not one of: {valid}"
        raise ValueError(msg) from None
