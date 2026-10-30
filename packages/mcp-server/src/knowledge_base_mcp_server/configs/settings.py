"""``McpServerSettings`` — where and how the knowledge base's endpoint is served."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from knowledge_base_config import BaseSettings, Environment, environment_from_env, load_settings


class McpServerSettings(BaseSettings):
    """Configuration for the knowledge base's MCP server."""

    yaml_directory: ClassVar[Path] = Path(__file__).parent

    # "http" serves streamable HTTP on host:port; "stdio" speaks JSON-RPC on
    # stdin/stdout so a client can spawn the process itself, with no daemon and
    # no port. MCP_TRANSPORT overrides, since a client config cannot edit YAML.
    transport: str
    host: str
    port: int
    path: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    log_level: str


def get_settings(env: Environment | None = None) -> McpServerSettings:
    """Load settings for ``env``, or the environment named by ``TOOLS_ENV`` if omitted.

    Example:
        >>> get_settings(Environment.TESTING).port
        9798
    """
    return load_settings(McpServerSettings, env=env or environment_from_env())
