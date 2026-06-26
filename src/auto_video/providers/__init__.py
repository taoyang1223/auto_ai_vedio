from __future__ import annotations

from .mock import MockProvider


def get_provider(name: str):
    if name == "mock":
        return MockProvider()
    raise KeyError(f"provider {name!r} is not available in this build")
