"""The YAML layers, read directly: tests never load the deployed environment by name."""

from __future__ import annotations

from omegaconf import OmegaConf

from tools_knowledge_base_api.configs.settings import KnowledgeBaseApiSettings

_CONFIGS = KnowledgeBaseApiSettings.yaml_directory


def _layers(*names: str) -> KnowledgeBaseApiSettings:
    merged = OmegaConf.merge(
        *(OmegaConf.load(_CONFIGS / n / "knowledge_base_api.yaml") for n in names)
    )
    return KnowledgeBaseApiSettings.model_validate(OmegaConf.to_object(merged))


def test_the_container_answers_only_localhost_on_port_8000() -> None:
    """compose publishes 127.0.0.1:8000 and its healthcheck sends ``Host: 127.0.0.1``."""
    base = _layers("base")

    assert not (_CONFIGS / "prod").exists(), "the container runs on base alone"
    assert (base.host, base.port) == ("0.0.0.0", 8000)
    assert base.allowed_hosts == ("localhost", "127.0.0.1")


def test_local_binds_loopback_only() -> None:
    assert _layers("base", "local").host == "127.0.0.1"
