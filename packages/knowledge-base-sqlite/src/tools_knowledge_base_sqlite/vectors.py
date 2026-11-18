"""Vector checks and cosine scoring for ``SqliteStore``: a vector that cannot be scored raises."""

from __future__ import annotations

import math
from array import array
from collections.abc import Sequence

from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid


def norm_of(vector: Sequence[float], dimensions: int) -> float:
    """The length of ``vector``; a wrong dimension or a zero or non-finite length raises."""
    if len(vector) != dimensions:
        msg = f"a {len(vector)}-dimension vector does not fit a {dimensions}-dimension collection"
        raise KnowledgeBaseError(msg)
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        msg = f"a vector of length {norm} has no cosine similarity"
        raise KnowledgeBaseError(msg)
    return norm


def pack(vector: Sequence[float], dimensions: int) -> bytes:
    """``vector`` as float32 bytes, after the checks of ``norm_of`` on the float32 values.

    Checking the float32 values, not the doubles, refuses a component that overflows to
    infinity or a vector that underflows to zero, which ``search`` could never score.
    """
    packed = array("f", vector)
    _ = norm_of(packed, dimensions)
    return packed.tobytes()


def cosine(query: Sequence[float], query_norm: float, blob: bytes, row_id: str) -> float:
    """Cosine similarity of ``query`` to the stored ``blob``; an unscorable blob raises."""
    stored = array("f")
    stored.frombytes(blob)
    length = math.hypot(*stored)
    if len(stored) != len(query) or not math.isfinite(length) or length == 0:
        msg = (
            f"row {row_id} holds a {len(stored)}-dimension embedding of length {length}; "
            f"the query has {len(query)} dimensions"
        )
        raise StoredItemInvalid(msg)
    return math.sumprod(query, stored) / (query_norm * length)
