"""The installed kinds and the JSON Schema of each one's payload."""

from __future__ import annotations

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import KindSchema


def list_memory_kinds(kb: KnowledgeBase) -> list[KindSchema]:
    """Every installed kind, in name order."""
    return [
        KindSchema(
            name=kind.name,
            payload_schema=kind.payload_model.model_json_schema(),
            max_chars=kb.settings.item_limits.for_kind(kind.name),
        )
        for kind in kb.kinds
    ]
