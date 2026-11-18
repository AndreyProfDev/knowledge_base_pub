"""Refusals every surface shares: a keyless embedder (at its first use), no memory kinds."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from knowledge_base_config.resolvers import kb_data_dir
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.registry import KindRegistry


class _HasKinds(Protocol):
    """What ``require_kinds`` reads of a ``KnowledgeBase``; naming it would import ``context``."""

    @property
    def kinds(self) -> KindRegistry:
        """The installed memory kinds."""
        ...


# OPEN_AI_API_KEY supplies the key of an embedder served by OpenAI itself.
_OPENAI_HOST = "api.openai.com"


def require_embedder_key(settings: KnowledgeBaseSettings) -> None:
    """Raise ``KnowledgeBaseError`` if the active embedder has an empty ``api_key``."""
    embeddings = settings.embeddings
    embedder = embeddings.active_embedder
    if embedder.api_key.get_secret_value():
        return
    remedy = (
        f"set OPEN_AI_API_KEY in the environment or in {Path(kb_data_dir()) / '.env'}"
        if urlsplit(embedder.base_url).hostname == _OPENAI_HOST
        else f"set embeddings.embedders.{embeddings.active}.api_key"
    )
    msg = (
        f"active embedder {embeddings.active!r} ({embedder.model} at "
        f"{embedder.base_url}) has an empty api_key: {remedy}"
    )
    raise KnowledgeBaseError(msg)


def require_kinds(kb: _HasKinds) -> None:
    """Raise ``KnowledgeBaseError`` if ``kb`` has no memory kind installed."""
    if not kb.kinds.names():
        msg = (
            "no memory kinds installed: install a kind package, "
            "such as tools-knowledge-base-knowledge"
        )
        raise KnowledgeBaseError(msg)
