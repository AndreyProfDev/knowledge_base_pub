"""``workflow``: a named, ordered list of steps, keyed by its ``name``."""

from __future__ import annotations

import unicodedata
from typing import Annotated

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


def _one_non_blank_line(value: str) -> str:
    # ``render`` is the name header plus exactly one line per step, so a step or name must
    # not carry a line break (the description may: ``render`` joins its lines into one).
    # ``splitlines`` knows every line boundary (\v, \f, \x1c-\x1e, \x85, the Unicode
    # separators), not just \n and \r; comparing with ``[value]`` also rejects a trailing one.
    if value.splitlines() != [value] or not _has_visible_char(value):
        msg = "must be one non-blank line"
        raise ValueError(msg)
    return value


class WorkflowPayload(BaseModel):
    """One workflow; ``name`` is its identity and ``steps`` keep their order."""

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
    description: str = Field(
        default="",
        description="Optional. Replaced along with the whole workflow on update.",
        json_schema_extra={"x-long-text": True},
    )
    steps: list[
        Annotated[
            str,
            StringConstraints(min_length=1),
            AfterValidator(_one_non_blank_line),
            # ``title`` is the UI hint for one entry of the list.
            Field(title="Step"),
        ]
    ] = Field(
        min_length=1,
        description=(
            "One or more steps, in order — on the CLI repeat --steps once per step;"
            " each a single non-blank line."
        ),
    )


def _header(name: str, description: str) -> str:
    """``name: description``, or just ``name`` when the description has nothing visible."""
    return f"{name}: {description}" if _has_visible_char(description) else name


def _workflow(payload: BaseModel) -> WorkflowPayload:
    if not isinstance(payload, WorkflowPayload):
        msg = f"workflow kind got a {type(payload).__name__} payload"
        raise TypeError(msg)
    return payload


class WorkflowKind:
    """The ``workflow`` ``MemoryKind``: upsert by ``name``."""

    def __init__(self) -> None:
        self.name = "workflow"
        self.payload_model: type[BaseModel] = WorkflowPayload
        self.counted_over = "name: description (or name), then one step per line"
        self.oversize_hint = (
            "Name, description and steps count together: shorten them, "
            "or split it into several smaller workflows."
        )

    def key(self, payload: BaseModel) -> str:
        """The workflow's ``name``."""
        return _workflow(payload).name

    def embed_text(self, payload: BaseModel) -> str:
        """The header (``name: description``, or ``name``), then one step per line."""
        workflow = _workflow(payload)
        return "\n".join([_header(workflow.name, workflow.description), *workflow.steps])

    def render(self, payload: BaseModel) -> str:
        """The header on one line, then the steps numbered from 1, one per line.

        The description's line breaks become spaces, so it cannot pass for a step.
        """
        workflow = _workflow(payload)
        header = _header(workflow.name, " ".join(workflow.description.splitlines()))
        numbered = [f"{number}. {step}" for number, step in enumerate(workflow.steps, start=1)]
        return "\n".join([header, *numbered])
