"""Shared reactive OpenAI backoff for 21 worker threads.

No invented RPM/TPM threshold: SDK handles per-request retries and API headers;
terminal 429 Retry-After applies as a shared cool-down across workers.
"""
from __future__ import annotations
import datetime as dt
import email.utils
import threading
import time

class SharedCooldown:
    def __init__(self):
        self._lock = threading.RLock()
        self._until = 0.0
    def before_request(self):
        while True:
            with self._lock:
                remaining = self._until - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 5.0))
    def rate_limited(self, headers=None):
        headers = headers or {}
        value = headers.get('retry-after') or headers.get('Retry-After') or ''
        seconds = 2.0
        try: seconds = float(value)
        except (TypeError, ValueError):
            try:
                date = email.utils.parsedate_to_datetime(value)
                seconds = (date - dt.datetime.now(dt.timezone.utc)).total_seconds()
            except (TypeError, ValueError): pass
        seconds = min(max(seconds, 0.2), 300.0)
        with self._lock:
            self._until = max(self._until, time.monotonic() + seconds)

GLOBAL_OPENAI_COOLDOWN = SharedCooldown()

try:
    from openai import OpenAI, RateLimitError
    class CoordinatedOpenAI(OpenAI):
        def request(self, *args, **kwargs):
            GLOBAL_OPENAI_COOLDOWN.before_request()
            try:
                return super().request(*args, **kwargs)
            except RateLimitError as exc:
                response = getattr(exc, 'response', None)
                GLOBAL_OPENAI_COOLDOWN.rate_limited(getattr(response, 'headers', None))
                raise
except ImportError:
    # Preserve a clear, normal dependency error on systems without the SDK.
    class CoordinatedOpenAI:
        def __init__(self, *args, **kwargs):
            raise ImportError('Install openai from requirements.txt before live runs')
