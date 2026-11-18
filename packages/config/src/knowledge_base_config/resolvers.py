"""OmegaConf custom resolvers: ``${secret:...}`` and ``${package_dir:...}``.

``${secret:<name>}`` reads ``os.environ[<name>.upper()]``, so a YAML line
``token: ${secret:gh_token}`` is satisfied by the ``GH_TOKEN`` environment
variable. ``${secret:<name>,<default>}`` falls back to ``<default>`` instead of
raising — useful for optional secrets, and for keeping settings introspectable
on a machine that has no credentials.

Secrets reach the process the same way in every environment: exported in the
shell, pre-seeded from ``.env`` (LOCAL only), or injected by whatever launches
the process. There is no encrypted-file or keychain tier in this workspace.

``${package_dir:<import_name>}`` returns an installed package's directory, so
package-internal data is addressed relative to the package rather than the
workspace.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from omegaconf import OmegaConf


class SecretNotFoundError(KeyError):
    """Raised when ``${secret:<name>}`` finds no value and has no default."""


class PackageNotFoundError(KeyError):
    """Raised when ``${package_dir:<name>}`` cannot locate an installed package."""


def register_resolvers() -> None:
    """Register this module's resolvers with OmegaConf, replacing any prior ones.

    Called on every ``load_settings`` so resolver names stay stable without a
    module-level singleton.
    """
    OmegaConf.register_new_resolver("secret", read_secret, replace=True)
    OmegaConf.register_new_resolver("package_dir", package_dir, replace=True)
    OmegaConf.register_new_resolver("kb_data_dir", kb_data_dir, replace=True)


def kb_data_dir(*_ignored: str) -> str:
    """Return the absolute directory the knowledge base keeps its data in.

    ``KB_DATA_DIR`` wins, then ``$XDG_DATA_HOME/knowledge-base``, then
    ``~/.local/share/knowledge-base``. An empty variable counts as unset and a
    relative one is resolved against the current directory. The resolver is
    written ``${kb_data_dir:}``; OmegaConf passes it an empty argument, ignored.

    Example:
        >>> kb_data_dir()  # doctest: +SKIP
        '/home/me/.local/share/knowledge-base'
    """
    explicit = os.environ.get("KB_DATA_DIR")
    if explicit:
        return str(Path(explicit).absolute())
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return str(Path(xdg).absolute() / "knowledge-base")
    return str(Path.home() / ".local" / "share" / "knowledge-base")


def read_secret(name: str, default: str | None = None) -> str:
    """Return the secret ``name`` from the environment, or ``default``.

    Example:
        >>> os.environ["GH_TOKEN"] = "ghp_example"
        >>> read_secret("gh_token")
        'ghp_example'
    """
    env_var = name.upper()
    value = os.environ.get(env_var)
    if value:
        return value
    if default is not None:
        return default
    msg = (
        f"secret {name!r} not found: set the {env_var} environment variable, "
        f"or add {env_var}=... to {Path(kb_data_dir()) / '.env'}"
    )
    raise SecretNotFoundError(msg)


def package_dir(import_name: str) -> str:
    """Return the absolute directory of an installed package.

    Example:
        >>> package_dir("knowledge_base_config")  # doctest: +SKIP
        '/.../packages/config/src/knowledge_base_config'
    """
    spec = importlib.util.find_spec(import_name)
    if spec is None or spec.origin is None:
        msg = f"package {import_name!r} not found"
        raise PackageNotFoundError(msg)
    return str(Path(spec.origin).parent)
