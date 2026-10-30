"""``${package_dir:...}`` resolves through ``load_settings``, not only when called directly."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from knowledge_base_config import BaseSettings, Environment, load_settings
from knowledge_base_config.resolvers import package_dir


def test_package_dir_resolves_inside_a_loaded_yaml(tmp_path: Path) -> None:
    class _Settings(BaseSettings):
        yaml_directory: ClassVar[Path] = tmp_path

        name: str

    base = tmp_path / "base"
    base.mkdir()
    (base / "a.yaml").write_text("name: ${package_dir:knowledge_base_config}\n", encoding="utf-8")

    loaded = load_settings(_Settings, env=Environment.TESTING)

    assert loaded.name == package_dir("knowledge_base_config")
