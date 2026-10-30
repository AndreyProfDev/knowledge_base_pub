"""Loader behaviour: layering, resolvers, and failure modes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

import pytest

from knowledge_base_config import BaseSettings, Environment, SecretNotFoundError, load_settings


def _make_settings_class(yaml_dir: Path) -> type[Any]:
    class _Settings(BaseSettings):
        yaml_directory: ClassVar[Path] = yaml_dir

        name: str
        count: int = 0

    return _Settings


def test_env_layer_overrides_base(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    (configs / "base").mkdir(parents=True)
    (configs / "testing").mkdir()
    (configs / "base" / "a.yaml").write_text("name: base\ncount: 1\n", encoding="utf-8")
    (configs / "testing" / "a.yaml").write_text("name: overlay\n", encoding="utf-8")

    settings = load_settings(_make_settings_class(configs), env=Environment.TESTING)

    assert settings.name == "overlay"
    assert settings.count == 1, "keys absent from the overlay must survive from base"


def test_settings_are_frozen(tmp_path: Path) -> None:
    configs = tmp_path / "configs" / "base"
    configs.mkdir(parents=True)
    (configs / "a.yaml").write_text("name: x\n", encoding="utf-8")

    settings = load_settings(_make_settings_class(tmp_path / "configs"), env=Environment.TESTING)

    with pytest.raises(Exception, match=r"frozen|Instance is frozen"):
        settings.name = "mutated"


def test_secret_resolver_reads_upper_cased_env_var(tmp_path: Path) -> None:
    configs = tmp_path / "configs" / "base"
    configs.mkdir(parents=True)
    (configs / "a.yaml").write_text("name: ${secret:my_thing}\n", encoding="utf-8")

    os.environ["MY_THING"] = "resolved"
    try:
        settings = load_settings(
            _make_settings_class(tmp_path / "configs"), env=Environment.TESTING
        )
    finally:
        del os.environ["MY_THING"]

    assert settings.name == "resolved"


def test_oc_env_resolver_reads_env_var(tmp_path: Path) -> None:
    configs = tmp_path / "configs" / "base"
    configs.mkdir(parents=True)
    (configs / "a.yaml").write_text("name: ${oc.env:MY_OVERRIDE,fallback}\n", encoding="utf-8")

    os.environ["MY_OVERRIDE"] = "from-env"
    try:
        settings = load_settings(
            _make_settings_class(tmp_path / "configs"), env=Environment.TESTING
        )
    finally:
        del os.environ["MY_OVERRIDE"]

    assert settings.name == "from-env"


def test_secret_resolver_raises_with_actionable_message(tmp_path: Path) -> None:
    configs = tmp_path / "configs" / "base"
    configs.mkdir(parents=True)
    (configs / "a.yaml").write_text("name: ${secret:definitely_absent}\n", encoding="utf-8")

    with pytest.raises(SecretNotFoundError, match="DEFINITELY_ABSENT"):
        load_settings(_make_settings_class(tmp_path / "configs"), env=Environment.TESTING)


def test_missing_yaml_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no YAML found"):
        load_settings(_make_settings_class(tmp_path / "nope"), env=Environment.TESTING)
