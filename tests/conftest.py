"""Test fixtures. Network access is blocked for the whole suite."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field

import pytest

from translation_tool.providers import ProviderError, UnsupportedLanguageError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if any test tries to open a real connection."""

    def guard(*args, **kwargs):
        raise RuntimeError("Network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@dataclass
class FakeProvider:
    """Scriptable provider: returns ``[target] text`` or raises queued errors."""

    name: str = "Fake"
    max_chars: int = 5000
    needs_source: bool = False
    errors: list[Exception] = field(default_factory=list)
    delay: float = 0.0
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    def translate(self, text: str, source: str, target: str) -> str:
        self.calls.append((text, source, target))
        if self.delay:
            import time

            time.sleep(self.delay)
        if self.errors:
            raise self.errors.pop(0)
        return f"[{target}] {text}"


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def transient() -> ProviderError:
    return ProviderError("Fake: rate limited", transient=True)


@pytest.fixture
def unsupported() -> UnsupportedLanguageError:
    return UnsupportedLanguageError("Fake: language not supported")
