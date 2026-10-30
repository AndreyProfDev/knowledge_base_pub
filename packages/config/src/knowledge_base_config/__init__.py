"""Structured settings: frozen pydantic classes loaded from layered YAML."""

from knowledge_base_config.base_settings import BaseSettings
from knowledge_base_config.environment import TOOLS_ENV_VAR, Environment, environment_from_env
from knowledge_base_config.loader import load_settings
from knowledge_base_config.resolvers import (
    PackageNotFoundError,
    SecretNotFoundError,
    package_dir,
    read_secret,
)

__all__ = [
    "TOOLS_ENV_VAR",
    "BaseSettings",
    "Environment",
    "PackageNotFoundError",
    "SecretNotFoundError",
    "environment_from_env",
    "load_settings",
    "package_dir",
    "read_secret",
]
