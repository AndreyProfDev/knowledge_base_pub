"""Startup refusals every surface shares: a keyless embedder, no memory kinds."""

from __future__ import annotations

from urllib.parse import urlsplit

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import KnowledgeBaseError

# OPEN_AI_API_KEY supplies the key of an embedder served by OpenAI itself.
_OPENAI_HOST = "api.openai.com"


def require_embedder_key(settings: KnowledgeBaseSettings) -> None:
    """Raise ``KnowledgeBaseError`` if the active embedder has an empty ``api_key``."""
    embeddings = settings.embeddings
    embedder = embeddings.active_embedder
    if embedder.api_key.get_secret_value():
        return
    remedy = (
        "set OPEN_AI_API_KEY"
        if urlsplit(embedder.base_url).hostname == _OPENAI_HOST
        else f"set embeddings.embedders.{embeddings.active}.api_key"
    )
    msg = (
        f"active embedder {embeddings.active!r} ({embedder.model} at "
        f"{embedder.base_url}) has an empty api_key: {remedy}"
    )
    raise KnowledgeBaseError(msg)


def require_kinds(kb: KnowledgeBase) -> None:
    """Raise ``KnowledgeBaseError`` if ``kb`` has no memory kind installed."""
    if not kb.kinds.names():
        msg = (
            "no memory kinds installed: install a kind package, "
            "such as tools-knowledge-base-knowledge"
        )
        raise KnowledgeBaseError(msg)
