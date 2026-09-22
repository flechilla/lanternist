"""Remote model providers: OpenRouter for the writer, fal.ai for media.

Both clients talk plain httpx, so in fake mode (LANTERNIST_FAKE_ENGINES=1) and in tests they run
against an in-process fake of both services (fake.py), with every line of the real client code.
"""

import random

import httpx

from ..config import Settings


class ProviderError(RuntimeError):
    """A failed call to a remote provider, with what's needed to decide whether to retry."""

    def __init__(self, message: str, *, status: int | None = None, type: str | None = None,
                 retryable: bool = False, retry_after: float | None = None, meta: dict | None = None):
        super().__init__(message)
        self.status, self.type, self.retryable = status, type, retryable
        self.retry_after, self.meta = retry_after, meta or {}


_fake = None


def transport(cfg: Settings) -> httpx.AsyncBaseTransport | None:
    """The fake fal and OpenRouter in fake mode; None means the real network."""
    global _fake
    if not cfg.fake_engines:
        return None
    if _fake is None:
        from .fake import FakeWorld

        _fake = FakeWorld()
    return _fake.transport()


def fake_world():
    """The fake services behind fake mode, for tests to inspect or steer."""
    return _fake


def reset_fake() -> None:
    global _fake
    _fake = None


def backoff(attempt: int, retry_after: float | None = None, cap: float = 30.0) -> float:
    """Seconds to wait before retry number `attempt` (0-based), honouring a Retry-After."""
    if retry_after is not None:
        return min(max(retry_after, 0.0), cap * 2)
    return min(cap, 0.5 * 2 ** attempt) * random.uniform(0.8, 1.2)


def retry_after(r: httpx.Response) -> float | None:
    try:
        return float(r.headers["retry-after"])
    except (KeyError, ValueError):
        return None
