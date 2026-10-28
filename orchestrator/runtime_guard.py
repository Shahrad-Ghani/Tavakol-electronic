from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


@dataclass
class FailureClass:
    kind: str
    service: str
    fatal: bool
    retryable: bool
    message: str


def _text(exc: BaseException) -> str:
    parts = [type(exc).__name__, str(exc)]
    for name in ("code", "body", "response"):
        try:
            value = getattr(exc, name, None)
            if value:
                parts.append(str(value))
        except Exception:
            pass
    return " | ".join(parts).casefold()


def classify_exception(exc: BaseException, service_hint: str = "unknown") -> FailureClass:
    text = _text(exc)
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)

    if status in (401, 403) or any(k in text for k in (
        "invalid api key", "incorrect api key", "authentication", "unauthorized",
        "authorization has been denied", "api key is invalid", "api key is missing",
        "api key is required", "api_key is missing", "api_key is required",
    )):
        return FailureClass("API_AUTH_INVALID", service_hint, True, False, str(exc))

    if status == 429 and any(k in text for k in (
        "insufficient_quota", "billing", "credit", "quota exceeded", "hard limit",
    )):
        return FailureClass("API_CREDIT_EXHAUSTED", service_hint, True, False, str(exc))

    if any(k in text for k in (
        "insufficient_quota", "billing_hard_limit", "credit balance", "account balance",
        "quota has been exceeded", "quota exceeded", "api credit", "daily request limit",
        "daily search api", "search api call limit", "api call limit exceeded",
    )):
        return FailureClass("API_CREDIT_EXHAUSTED", service_hint, True, False, str(exc))

    if status == 429:
        return FailureClass("RATE_LIMIT", service_hint, False, True, str(exc))

    if status is not None and int(status) >= 500:
        return FailureClass("SERVICE_TEMPORARY", service_hint, False, True, str(exc))

    if any(k in text for k in (
        "connectionerror", "connecttimeout", "readtimeout", "timeout", "proxyerror",
        "name resolution", "temporary failure", "network is unreachable", "connection reset",
        "connection aborted", "failed to establish a new connection", "could not connect",
        "none of the configured proxies could connect",
    )):
        return FailureClass("NETWORK_OFFLINE", service_hint, False, True, str(exc))

    return FailureClass("NON_TRANSIENT_ERROR", service_hint, False, False, str(exc))


def host_reachable(host: str, port: int = 443, timeout: float = 4.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class RuntimeStop(RuntimeError):
    pass


class RecoveryController:
    """Shared pause/stop controller. Network failures auto-resume; auth/credit stops."""

    def __init__(self, logger, retry_seconds: float = 10.0):
        self.logger = logger
        self.retry_seconds = max(float(retry_seconds), 2.0)
        self.stop_requested = False
        self.manual_pause = False
        self.fatal_failure: Optional[FailureClass] = None

    def request_pause(self):
        self.manual_pause = True
        self.logger.emit("SYS", "WARN", "-", "PAUSE", "manual pause requested")

    def request_resume(self):
        self.manual_pause = False
        self.logger.emit("SYS", "OK", "-", "RESUME", "manual pause cleared")

    def request_stop(self):
        self.stop_requested = True
        self.logger.emit("SYS", "WARN", "-", "STOP", "stop requested")

    def wait_manual(self):
        while self.manual_pause and not self.stop_requested and not self.fatal_failure:
            time.sleep(0.25)
        if self.stop_requested or self.fatal_failure:
            raise RuntimeStop("pipeline stopped")

    def stop_for_fatal(self, failure: FailureClass, phase: str, item: str):
        self.fatal_failure = failure
        self.logger.emit(
            phase, "ERROR", item, failure.kind,
            f"{failure.service} | pipeline stopped | {failure.message}",
        )
        raise RuntimeStop(failure.kind)

    def wait_network_recovery(self, phase: str, item: str, service: str, checker):
        self.logger.emit(phase, "WARN", item, "PAUSED_NETWORK", f"{service} unavailable; waiting for recovery")
        while not self.stop_requested and not self.fatal_failure:
            self.wait_manual()
            try:
                if checker():
                    self.logger.emit(phase, "OK", item, "NETWORK_RECOVERED", f"{service} recovered; resuming from checkpoint")
                    return
            except Exception:
                pass
            time.sleep(self.retry_seconds)
        raise RuntimeStop("pipeline stopped")
