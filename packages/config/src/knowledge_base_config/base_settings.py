"""``BaseSettings`` — common parent for every package's ``*Settings`` class.

Carries the ``yaml_directory`` contract so :func:`knowledge_base_config.loader.load_settings`
can read it as a statically-typed attribute instead of a duck-typed lookup.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class BaseSettings(BaseModel):
    """Frozen pydantic base; subclasses set ``yaml_directory`` to their YAML root.

    Frozen because settings are read many times from many places and must not
    drift at runtime — an override belongs in a YAML overlay, not an attribute
    assignment.
    """

    model_config = ConfigDict(frozen=True)

    yaml_directory: ClassVar[Path]
