from __future__ import annotations

from auto_video.errors import ConfigError
from auto_video.models import ProviderConfig

from .external_command import ExternalCommandProvider
from .local_tts import LocalTTSProvider
from .mock import MockProvider


def get_provider(name: str, config: ProviderConfig | None = None):
    if name == "mock":
        return MockProvider()
    if name == "local_tts" or (config and config.mode == "local_tts"):
        return LocalTTSProvider(name, config)
    if config and config.mode == "external_command":
        return ExternalCommandProvider(name, config)
    raise ConfigError(
        f"provider {name!r} is not available in this build",
        fix="Use the mock/local_tts provider or configure providers.<name>.mode: external_command.",
    )
