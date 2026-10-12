"""Central configuration: limits, timeouts, retries and defaults."""

from __future__ import annotations

#: Maximum characters accepted from the user in one translation.
MAX_CHARS: int = 5000

#: Seconds to wait for a single provider request before giving up on it.
REQUEST_TIMEOUT_S: float = 10.0

#: Extra attempts per provider for transient failures (rate limit, network).
RETRIES: int = 1

#: Base delay between retries; attempt *n* waits ``RETRY_BACKOFF_S * n``.
RETRY_BACKOFF_S: float = 0.75

#: Number of distinct translations kept in the in-memory LRU cache.
CACHE_SIZE: int = 256

#: Translation history entries kept per browser session.
HISTORY_SIZE: int = 10

DEFAULT_SOURCE: str = "auto"
DEFAULT_TARGET: str = "hi"

#: Seconds to wait for the text-to-speech service.
TTS_TIMEOUT_S: float = 15.0
