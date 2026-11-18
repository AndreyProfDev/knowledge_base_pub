"""``${package_dir:...}`` resolves through ``load_settings``, not only when called directly."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import ClassVar

import pytest

from knowledge_base_config import BaseSettings, Environment, load_settings
from knowledge_base_config.resolvers import SecretNotFoundError, package_dir, read_secret


def test_a_missing_secret_names_the_dotenv_in_the_data_directory(tmp_path: Path) -> None:
    previous = os.environ["KB_DATA_DIR"]
    os.environ["KB_DATA_DIR"] = str(tmp_path)
    try:
        with pytest.raises(SecretNotFoundError, match=re.escape(f"{tmp_path}/.env")):
            read_secret("absent_probe_secret")
    finally:
        os.environ["KB_DATA_DIR"] = previous


def test_package_dir_resolves_inside_a_loaded_yaml(tmp_path: Path) -> None:
    class _Settings(BaseSettings):
        yaml_directory: ClassVar[Path] = tmp_path

        name: str

    base = tmp_path / "base"
    base.mkdir()
    (base / "a.yaml").write_text("name: ${package_dir:knowledge_base_config}\n", encoding="utf-8")

    loaded = load_settings(_Settings, env=Environment.TESTING)

    assert loaded.name == package_dir("knowledge_base_config")
