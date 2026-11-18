"""Typed errors for the knowledge base."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError


class KnowledgeBaseError(Exception):
    """Base class for every failure raised by this package."""


class UnknownKind(KnowledgeBaseError):  # noqa: N818 - the spec's name, shared with the REST layer
    """The request names a memory kind no installed package provides."""


class UnknownRequest(KnowledgeBaseError):  # noqa: N818 - sibling of UnknownKind
    """No request with the given id was ever queued on this knowledge base."""


class ItemNotFound(KnowledgeBaseError):  # noqa: N818 - the spec's name, shared with the REST layer
    """No item of the given kind has the given id."""


class WarmupDirectoryMissing(KnowledgeBaseError):  # noqa: N818 - sibling of ItemNotFound
    """The configured ``warmup.path`` is not a directory, or cannot be listed."""


class WarmupDirectoryEmpty(KnowledgeBaseError):  # noqa: N818 - sibling of WarmupDirectoryMissing
    """``warmup.path`` holds no items: a wrong path or an unfilled bind mount, not a 0-item run."""


class WarmupDumpFailed(KnowledgeBaseError):  # noqa: N818 - sibling of WarmupDirectoryMissing
    """A dump file could not be written or removed; the message names the file.

    A failed request's status carries only the exception's type and message, so an
    ``OSError`` alone can lose the path.
    """


class WarmupPartiallyWritten(KnowledgeBaseError):  # noqa: N818 - sibling of WarmupDumpFailed
    """A warm-up batch failed to embed or write; the batches before it stay written."""

    def __init__(self, written: int, kind: str, batch: int, cause: Exception) -> None:
        super().__init__(
            f"warm-up stopped at {kind} batch {batch} after writing {written} items: "
            f"{type(cause).__name__}: {cause}"
        )


class WriteRefused(KnowledgeBaseError):  # noqa: N818 - sibling of WarmupDumpFailed
    """A queued write that no retry can fix: unknown kind, invalid payload, or a stale write."""


class StoredItemInvalid(KnowledgeBaseError):  # noqa: N818 - sibling of ItemNotFound
    """A stored item or payload fails its model: schema drift or corruption, not caller input."""


def stored_as[M: BaseModel](model: type[M], data: object, where: str) -> M:
    """``data`` validated as ``model``.

    Raises:
        StoredItemInvalid: ``data`` fails ``model``; ``where`` identifies what was read.
    """
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        # No input: the stored data may be large or private; the id in ``where`` finds it.
        msg = f"{where}: {exc.errors(include_url=False, include_input=False)}"
        raise StoredItemInvalid(msg) from exc
