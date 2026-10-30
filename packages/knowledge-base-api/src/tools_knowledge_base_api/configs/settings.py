"""``KnowledgeBaseApiSettings`` — where the REST server listens and which hosts it answers."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from knowledge_base_config import BaseSettings, Environment, environment_from_env, load_settings


class KnowledgeBaseApiSettings(BaseSettings):
    """Configuration for the knowledge base REST server."""

    yaml_directory: ClassVar[Path] = Path(__file__).parent

    host: str
    port: int
    # TrustedHostMiddleware matches the Host header without its port.
    allowed_hosts: tuple[str, ...]


def get_settings(env: Environment | None = None) -> KnowledgeBaseApiSettings:
    """Load settings for ``env``, or the environment named by ``TOOLS_ENV`` if omitted.

    Example:
        >>> get_settings(Environment.TESTING).allowed_hosts[-1]
        'testserver'
    """
    return load_settings(KnowledgeBaseApiSettings, env=env or environment_from_env())
