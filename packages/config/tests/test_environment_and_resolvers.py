"""`environment_from_env`, `package_dir`, and the loader's failure modes.

This package owns the one module allowed to read `os.environ`, so its own tests
are the one place that may set environment variables directly — via the
`env_var` helper below, which restores the prior value in a `finally`. The
`no-os-environ` gate allows that here and nowhere else; every other package
injects a `settings=` override instead.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

import pytest
from omegaconf.errors import InterpolationResolutionError

from knowledge_base_config import BaseSettings, Environment, load_settings
from knowledge_base_config.environment import TOOLS_ENV_VAR, environment_from_env
from knowledge_base_config.resolvers import PackageNotFoundError, package_dir


@contextmanager
def env_var(name: str, value: str | None) -> Generator[None]:
    """Set (or clear) one variable for the duration of the block, then restore it."""
    previous = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def settings_class(yaml_dir: Path) -> type[Any]:
    class _Settings(BaseSettings):
        yaml_directory: ClassVar[Path] = yaml_dir

        name: str

    return _Settings


class TestEnvironmentFromEnv:
    def test_an_unset_variable_defaults_to_local(self) -> None:
        with env_var(TOOLS_ENV_VAR, None):
            assert environment_from_env() is Environment.LOCAL

    def test_an_empty_variable_defaults_to_local(self) -> None:
        with env_var(TOOLS_ENV_VAR, ""):
            assert environment_from_env() is Environment.LOCAL

    def test_whitespace_only_defaults_to_local(self) -> None:
        with env_var(TOOLS_ENV_VAR, "   "):
            assert environment_from_env() is Environment.LOCAL

    def test_a_named_environment_is_returned(self) -> None:
        with env_var(TOOLS_ENV_VAR, "testing"):
            assert environment_from_env() is Environment.TESTING

    def test_case_and_padding_are_tolerated(self) -> None:
        """Deliberately "testing" rather than another name.

        TOOLS_ENV steers every cached settings object in the process — e.g.
        the `lru_cache` behind `tools_knowledge_base_api.app`'s settings. Any value other
        than the one the suite already runs under would, if it ever escaped
        this block or were read inside it, pin that singleton to the wrong
        overlay; "prod" would additionally resolve any `${secret:...}` in a
        prod YAML against a real credential. Using the ambient value makes a
        leak a no-op, and strip+lower is exercised either way.
        """
        with env_var(TOOLS_ENV_VAR, "  TESTING  "):
            assert environment_from_env() is Environment.TESTING

    def test_an_unknown_name_lists_the_valid_ones(self) -> None:
        """The message has to name the options, or the operator is left guessing."""
        with (
            env_var(TOOLS_ENV_VAR, "staging"),
            pytest.raises(ValueError, match="staging") as caught,
        ):
            environment_from_env()
        message = str(caught.value)
        assert "'staging'" in message
        assert "local, testing, prod" in message


class TestPackageDir:
    def test_returns_an_installed_packages_directory(self) -> None:
        found = Path(package_dir("knowledge_base_config"))
        assert found.is_dir()
        assert (found / "environment.py").is_file()

    def test_an_absent_package_raises(self) -> None:
        with pytest.raises(PackageNotFoundError, match="no_such_package_anywhere"):
            package_dir("no_such_package_anywhere")


class TestLoaderFailureModes:
    def test_a_directory_with_no_yaml_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "base").mkdir()
        with pytest.raises(RuntimeError, match="no YAML found"):
            load_settings(settings_class(tmp_path), env=Environment.TESTING)

    def test_a_missing_directory_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="no YAML found"):
            load_settings(settings_class(tmp_path), env=Environment.TESTING)

    def test_a_yaml_file_that_is_not_a_mapping_is_an_error(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base.mkdir()
        (base / "a.yaml").write_text("- one\n- two\n", encoding="utf-8")
        with pytest.raises(TypeError, match="expected a top-level mapping"):
            load_settings(settings_class(tmp_path), env=Environment.TESTING)

    def test_an_exported_variable_reaches_a_secret(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base.mkdir()
        (base / "a.yaml").write_text("name: ${secret:loader_probe,fallback}\n", encoding="utf-8")
        with env_var("LOADER_PROBE", "from-the-environment"):
            loaded = load_settings(settings_class(tmp_path), env=Environment.LOCAL)
        assert loaded.name == "from-the-environment"

    def test_local_pre_seeds_from_a_dotenv_file(self, tmp_path: Path) -> None:
        """LOCAL is the only overlay that reads .env.

        The file is written into `tmp_path` and the cwd moved there, rather than
        relying on the checkout having one: a developer's `.env` would make this
        pass locally and vanish in CI, where nothing is committed.
        """
        base = tmp_path / "base"
        base.mkdir()
        (base / "a.yaml").write_text("name: ${secret:loader_probe,fallback}\n", encoding="utf-8")
        (tmp_path / ".env").write_text("LOADER_PROBE=from-the-dotenv-file\n", encoding="utf-8")
        previous = Path.cwd()
        os.chdir(tmp_path)
        try:
            # `load_dotenv` writes into os.environ, so this also undoes that.
            with env_var("LOADER_PROBE", None):
                loaded = load_settings(settings_class(tmp_path), env=Environment.LOCAL)
        finally:
            os.chdir(previous)
        assert loaded.name == "from-the-dotenv-file"

    def test_an_exported_variable_beats_the_dotenv_file(self, tmp_path: Path) -> None:
        """`override=False`: the process environment wins, so CI can override .env."""
        base = tmp_path / "base"
        base.mkdir()
        (base / "a.yaml").write_text("name: ${secret:loader_probe,fallback}\n", encoding="utf-8")
        (tmp_path / ".env").write_text("LOADER_PROBE=from-the-dotenv-file\n", encoding="utf-8")
        previous = Path.cwd()
        os.chdir(tmp_path)
        try:
            with env_var("LOADER_PROBE", "exported"):
                loaded = load_settings(settings_class(tmp_path), env=Environment.LOCAL)
        finally:
            os.chdir(previous)
        assert loaded.name == "exported"

    def test_a_secret_with_a_default_survives_an_empty_environment(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base.mkdir()
        (base / "a.yaml").write_text("name: ${secret:loader_probe,fallback}\n", encoding="utf-8")
        with env_var("LOADER_PROBE", None):
            loaded = load_settings(settings_class(tmp_path), env=Environment.LOCAL)
        assert loaded.name == "fallback"

    def test_a_non_secret_interpolation_failure_keeps_its_own_type(self, tmp_path: Path) -> None:
        """Only SecretNotFoundError is unwrapped; anything else propagates as-is."""
        base = tmp_path / "base"
        base.mkdir()
        (base / "a.yaml").write_text("name: ${package_dir:no_such_pkg}\n", encoding="utf-8")
        with pytest.raises(InterpolationResolutionError):
            load_settings(settings_class(tmp_path), env=Environment.TESTING)

    def test_no_dotenv_anywhere_above_the_cwd_is_fine(self, tmp_path: Path) -> None:
        """`find_dotenv` returns "" outside the repo; LOCAL must still load."""
        base = tmp_path / "base"
        base.mkdir()
        (base / "a.yaml").write_text("name: plain\n", encoding="utf-8")
        previous = Path.cwd()
        os.chdir(tmp_path)
        try:
            loaded = load_settings(settings_class(tmp_path), env=Environment.LOCAL)
        finally:
            os.chdir(previous)
        assert loaded.name == "plain"
