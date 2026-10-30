"""Load a single settings class from its layered YAML.

Each package ships its own ``get_settings(env)`` that calls :func:`load_settings`
once. Layers merge lowest-to-highest: ``<yaml_directory>/base/*.yaml`` then
``<yaml_directory>/<env>/*.yaml``. Within a layer, files merge in sorted order.

In the LOCAL environment ``find_dotenv`` walks up for a ``.env`` and loads it
with ``override=False`` so an exported shell variable always wins.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from omegaconf import DictConfig, OmegaConf
from omegaconf.errors import InterpolationResolutionError

from knowledge_base_config.base_settings import BaseSettings
from knowledge_base_config.environment import Environment
from knowledge_base_config.resolvers import SecretNotFoundError, register_resolvers


def load_settings[T: BaseSettings](cls: type[T], *, env: Environment) -> T:
    """Merge ``base/`` and ``<env>/`` YAML under ``cls.yaml_directory`` and validate.

    Args:
        cls: The settings class; its ``yaml_directory`` names the config root.
        env: Which overlay directory to apply on top of ``base/``.

    Example:
        >>> load_settings(GithubSettings, env=Environment.TESTING)  # doctest: +SKIP
        GithubSettings(api_url='https://api.github.invalid', ...)
    """
    if env is Environment.LOCAL:
        _maybe_load_dotenv()
    register_resolvers()
    merged = _merge_yaml_layers(cls.yaml_directory, env)
    return cls.model_validate(_resolve(merged))


def _resolve(merged: DictConfig) -> object:
    """Materialise the config, restoring the resolver's own exception type.

    OmegaConf catches whatever a resolver raises and re-raises it as an
    ``InterpolationResolutionError`` with no ``__cause__`` — only the original
    class name in the message. Left alone, that would defeat every
    ``except SecretNotFoundError`` in the codebase, so a missing token would
    surface as an opaque interpolation failure instead of "set GH_TOKEN".
    """
    try:
        return OmegaConf.to_object(merged)
    except InterpolationResolutionError as exc:
        if str(exc).startswith(SecretNotFoundError.__name__):
            raise SecretNotFoundError(str(exc)) from exc
        raise


def _maybe_load_dotenv() -> None:
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path)


def _merge_yaml_layers(yaml_directory: Path, env: Environment) -> DictConfig:
    layers: list[DictConfig] = []
    for layer_dir in (yaml_directory / "base", yaml_directory / env.value):
        if layer_dir.is_dir():
            layers.extend(_load_yaml_files(layer_dir))
    if not layers:
        msg = f"no YAML found under {yaml_directory}"
        raise RuntimeError(msg)
    merged = OmegaConf.merge(*layers)
    if not isinstance(merged, DictConfig):  # pragma: no cover
        # Unreachable: `_load_dict_config` already rejects every non-mapping
        # layer, so merging them cannot produce one. Kept as a guard in case
        # that invariant is ever loosened.
        msg = f"{yaml_directory}: not a mapping"  # pragma: no mutate, equivalent: unreachable
        raise TypeError(msg)  # pragma: no mutate, equivalent: unreachable
    return merged


def _load_yaml_files(layer_dir: Path) -> list[DictConfig]:
    return [_load_dict_config(path) for path in sorted(layer_dir.glob("*.yaml"))]


def _load_dict_config(yaml_path: Path) -> DictConfig:
    config = OmegaConf.load(yaml_path)
    if not isinstance(config, DictConfig):
        msg = f"{yaml_path}: expected a top-level mapping"
        raise TypeError(msg)
    return config
