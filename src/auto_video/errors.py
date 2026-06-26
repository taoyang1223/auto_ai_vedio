from __future__ import annotations


class AutoVideoError(Exception):
    """Base class for user-facing auto-video errors."""

    category = "AutoVideoError"

    def __init__(self, message: str, *, fix: str | None = None):
        super().__init__(message)
        self.message = message
        self.fix = fix

    def __str__(self) -> str:
        if self.fix:
            return f"{self.category}: {self.message}\nFix: {self.fix}"
        return f"{self.category}: {self.message}"


class ConfigError(AutoVideoError):
    category = "ConfigError"


class AssetError(AutoVideoError):
    category = "AssetError"


class ProviderError(AutoVideoError):
    category = "ProviderError"


class RenderError(AutoVideoError):
    category = "RenderError"


class ProbeError(AutoVideoError):
    category = "ProbeError"
