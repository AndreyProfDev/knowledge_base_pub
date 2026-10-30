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

    huey records only the exception's ``repr``, so an ``OSError`` alone loses the path.
    """


class DumpRemovalNotQueued(KnowledgeBaseError):  # noqa: N818 - sibling of WarmupDumpFailed
    """The item was deleted, but queueing its dump file's removal failed.

    Not ``ItemNotFound``: a retry of the delete would get that, and the file would stay.
    """


class UnknownWarmupRun(KnowledgeBaseError):  # noqa: N818 - sibling of UnknownRequest
    """No warm-up run with the given id was recorded on this knowledge base."""


class WarmupPartiallyQueued(KnowledgeBaseError):  # noqa: N818 - sibling of WarmupDirectoryEmpty
    """An enqueue, or recording run ``run_id``, failed; ``problem`` says which and how far."""

    def __init__(self, run_id: str, problem: str, cause: Exception) -> None:
        self.run_id = run_id
        super().__init__(f"warm-up run {run_id} {problem}: {type(cause).__name__}: {cause}")


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
