"""``entity``: a named thing, keyed by its ``(name, type)`` pair."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

# Categories that never draw a glyph of their own: controls, format characters (a
# zero-width space), surrogates, private-use and unassigned code points, separators, and
# combining marks, which only decorate a base character.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zs", "Zl", "Zp", "Mn", "Me"})
# Letters and symbols Unicode files under visible categories that still render blank:
# the Hangul fillers, the braille blank and the Mongolian vowel separator.
_BLANK_GLYPHS = frozenset(
    "\N{HANGUL CHOSEONG FILLER}\N{HANGUL JUNGSEONG FILLER}\N{HANGUL FILLER}"
    "\N{HALFWIDTH HANGUL FILLER}\N{BRAILLE PATTERN BLANK}\N{MONGOLIAN VOWEL SEPARATOR}"
)


def _has_visible_char(text: str) -> bool:
    # A value made only of characters that draw nothing counts as blank, whatever
    # ``str.strip`` would say.
    return any(
        unicodedata.category(ch) not in _INVISIBLE_CATEGORIES and ch not in _BLANK_GLYPHS
        for ch in text
    )


def _not_blank(value: str) -> str:
    if not _has_visible_char(value):
        msg = "must not be blank"
        raise ValueError(msg)
    return value


def _one_non_blank_line(value: str) -> str:
    # ``render`` is one line, so a name must not carry a line break (the description may:
    # ``render`` joins its lines into one). ``splitlines`` knows every line boundary (\v, \f,
    # \x1c-\x1e, \x85, the Unicode separators), not just \n and \r; comparing with
    # ``[value]`` also rejects a trailing one.
    if value.splitlines() != [value] or not _has_visible_char(value):
        msg = "must be one non-blank line"
        raise ValueError(msg)
    return value


class EntityPayload(BaseModel):
    """One entity; ``name`` and ``type`` together are its identity."""

    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
        AfterValidator(_one_non_blank_line),
        Field(
            description=(
                "One non-blank line; surrounding whitespace is stripped, not part of the identity."
            )
        ),
    ]
    type: Literal["person", "system", "project", "concept", "organization", "tool"] = Field(
        description="What the entity is."
    )
    description: Annotated[
        str,
        Field(min_length=1, description="Non-blank.", json_schema_extra={"x-long-text": True}),
        AfterValidator(_not_blank),
    ]


def _entity(payload: BaseModel) -> EntityPayload:
    if not isinstance(payload, EntityPayload):
        msg = f"entity kind got a {type(payload).__name__} payload"
        raise TypeError(msg)
    return payload


class EntityKind:
    """The ``entity`` ``MemoryKind``: upsert by ``(name, type)``."""

    def __init__(self) -> None:
        self.name = "entity"
        self.payload_model: type[BaseModel] = EntityPayload
        self.counted_over = "name: description"
        self.oversize_hint = (
            "Keep the description to what the entity is; store further facts about it "
            "as separate knowledge items."
        )

    def key(self, payload: BaseModel) -> str:
        """``name`` and ``type`` joined by a unit separator.

        ``type`` is a closed set without the separator and comes last, so two
        distinct pairs never join to the same key.
        """
        entity = _entity(payload)
        return f"{entity.name}\x1f{entity.type}"

    def embed_text(self, payload: BaseModel) -> str:
        """``name: description``."""
        entity = _entity(payload)
        return f"{entity.name}: {entity.description}"

    def render(self, payload: BaseModel) -> str:
        """``name (type): description`` on one line; the description's line breaks become spaces."""
        entity = _entity(payload)
        description = " ".join(entity.description.splitlines())
        return f"{entity.name} ({entity.type}): {description}"
