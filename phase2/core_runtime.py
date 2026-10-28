from __future__ import annotations

from .logging_bridge import phase2_log

import getpass
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import quote, urlparse

import requests
from requests import Response, Session
from requests.exceptions import (
    ConnectTimeout,
    ConnectionError as RequestsConnectionError,
    ProxyError,
    ReadTimeout,
    RequestException,
    SSLError,
)

MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"
PROXY_TEST_URL = "https://api.mouser.com/api/docs/V1"
MAX_PARTS_PER_MOUSER_REQUEST = 10
MIN_SECONDS_BETWEEN_SEARCH_CALLS = 2.1
CONNECT_TIMEOUT = 12
READ_TIMEOUT = 35
ALLOW_PROXY_FAILOVER = True
CASE_SENSITIVE_PART_MATCH = False

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SearchRateLimiter:
    def __init__(self, min_interval: float = MIN_SECONDS_BETWEEN_SEARCH_CALLS):
        self.min_interval = min_interval
        self._last_call_started = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        remaining = self.min_interval - (now - self._last_call_started)
        if remaining > 0:
            time.sleep(remaining)
        self._last_call_started = time.monotonic()


def load_dotenv_simple(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def normalize_part_for_match(part_number: str) -> str:
    value = str(part_number or "").strip()
    return value if CASE_SENSITIVE_PART_MATCH else value.upper()


def validate_part_number_for_mouser(part_number: str) -> Optional[str]:
    if len(part_number) < 3:
        return "Part Number shorter than Mouser minimum of 3 characters"
    if len(part_number) > 40:
        return "Part Number longer than Mouser maximum of 40 characters"
    if "|" in part_number:
        return "Part Number contains pipe '|' which Mouser uses as batch delimiter"
    return None


def safe_filename(part_number: str) -> str:
    name = str(part_number or "").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    if not name:
        name = "unnamed_part"
    if name.upper() in WINDOWS_RESERVED_NAMES:
        name = f"_{name}"
    return name[:180]


def normalize_proxy_line(raw: str) -> Optional[str]:
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        parsed = urlparse(line)
        if not parsed.hostname or not parsed.port:
            raise ValueError("Proxy URL must contain host and port")
        return line
    if "@" in line:
        left, right = line.rsplit("@", 1)
        if ":" not in left or ":" not in right:
            raise ValueError("Invalid authenticated proxy format")
        user, password = left.split(":", 1)
        host, port = right.rsplit(":", 1)
        return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    parts = line.split(":")
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    if len(parts) >= 4:
        host, port, user = parts[0], parts[1], parts[2]
        password = parts[3] if len(parts) == 5 and parts[4] == port else ":".join(parts[3:])
        return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    raise ValueError("Unsupported proxy format")


def load_proxies(proxy_file: Path) -> List[str]:
    if not proxy_file.exists():
        raise FileNotFoundError(f"Proxy file not found: {proxy_file}")
    proxies: List[str] = []
    seen = set()
    for line_no, raw in enumerate(proxy_file.read_text(encoding="utf-8-sig").splitlines(), 1):
        try:
            proxy = normalize_proxy_line(raw)
        except Exception as exc:
            phase2_log(f"[PROXY-SKIP] line={line_no} reason={exc}")
            continue
        if proxy and proxy not in seen:
            seen.add(proxy)
            proxies.append(proxy)
    if not proxies:
        raise RuntimeError("No usable proxy entries found.")
    return proxies


def mask_proxy(proxy_url: str) -> str:
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        return "***"
    return f"{parsed.hostname}:{parsed.port or ''}"


class StickyProxySession:
    def __init__(self, proxies: Sequence[str]):
        self.proxies = list(proxies)
        self.failed = set()
        self.active_proxy: Optional[str] = None
        self.session: Optional[Session] = None

    def _new_session(self, proxy_url: str) -> Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131 Safari/537.36 "
                "TavakolElectronic-Phase2/1.0"
            ),
            "Accept": "*/*",
        })
        session.proxies.update({"http": proxy_url, "https": proxy_url})
        return session

    def select_initial_proxy(self) -> None:
        phase2_log(f"[PROXY] testing {len(self.proxies)} candidate(s)...")
        self._select_next_working_proxy()

    def _select_next_working_proxy(self) -> None:
        for proxy_url in self.proxies:
            if proxy_url in self.failed:
                continue
            session = self._new_session(proxy_url)
            label = mask_proxy(proxy_url)
            try:
                response = session.get(
                    PROXY_TEST_URL,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    allow_redirects=True,
                )
                if response.status_code == 200:
                    self.active_proxy = proxy_url
                    self.session = session
                    phase2_log(f"[PROXY-OK] selected={label}")
                    return
                phase2_log(f"[PROXY-FAIL] {label} http={response.status_code}")
            except RequestException as exc:
                phase2_log(f"[PROXY-FAIL] {label} error={type(exc).__name__}")
            self.failed.add(proxy_url)
            session.close()
        raise RuntimeError("None of the configured proxies could connect to Mouser.")

    def failover(self, reason: str) -> None:
        if not ALLOW_PROXY_FAILOVER:
            raise RuntimeError(f"Active proxy failed and failover is disabled: {reason}")
        if self.active_proxy:
            phase2_log(f"[PROXY-LOST] {mask_proxy(self.active_proxy)} reason={reason}")
            self.failed.add(self.active_proxy)
        if self.session:
            self.session.close()
        self.active_proxy = None
        self.session = None
        self._select_next_working_proxy()

    def request(self, method: str, url: str, **kwargs) -> Response:
        if not self.session or not self.active_proxy:
            raise RuntimeError("Proxy session is not initialized.")
        proxy_failure_types = (ProxyError, ConnectTimeout, RequestsConnectionError, SSLError)
        attempts = 0
        while True:
            attempts += 1
            try:
                response = self.session.request(method, url, **kwargs)
                if response.status_code == 407:
                    self.failover("HTTP 407 proxy authentication failure")
                    if attempts <= len(self.proxies):
                        continue
                return response
            except proxy_failure_types as exc:
                if attempts >= len(self.proxies):
                    raise
                self.failover(type(exc).__name__)


def chunks(items: Sequence[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield list(items[i:i + size])


def mouser_search_batch(
    proxy_session: StickyProxySession,
    api_key: str,
    batch: Sequence[str],
    rate_limiter: SearchRateLimiter,
) -> Dict[str, object]:
    if not batch:
        return {}
    if len(batch) > MAX_PARTS_PER_MOUSER_REQUEST:
        raise ValueError("Batch exceeds Mouser maximum of 10 part numbers.")
    payload = {
        "SearchByPartRequest": {
            "mouserPartNumber": "|".join(batch),
            "partSearchOptions": "Exact",
            "mouserPaysCustomsAndDuties": False,
        }
    }
    # Caller may already rate-limit batches; keep this guard for direct usage.
    rate_limiter.wait()
    last_error = None
    for attempt in range(1, 4):
        try:
            response = proxy_session.request(
                "POST", MOUSER_SEARCH_URL,
                params={"apiKey": api_key}, json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_s = max(float(retry_after), 3.0) if retry_after else 5.0
                except ValueError:
                    wait_s = 5.0
                phase2_log(f"[RATE-LIMIT] waiting {wait_s:.1f}s")
                time.sleep(wait_s)
                last_error = f"HTTP 429: {response.text[:300]}"
                continue
            if 500 <= response.status_code <= 599:
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if attempt < 3:
                    time.sleep(2 * attempt)
                    continue
            response.raise_for_status()
            data = response.json()
            api_errors = data.get("Errors") or []
            if api_errors:
                message = "; ".join(str(x.get("Message") or x.get("Code") or x) for x in api_errors)
                raise RuntimeError(f"Mouser API returned Errors: {message}")
            return data
        except (ReadTimeout, RequestException, ValueError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 3:
                time.sleep(2 * attempt)
                continue
            break
    raise RuntimeError(f"Mouser search failed after retries: {last_error}")


def index_exact_mouser_results(
    requested: Sequence[str], response_json: Dict[str, object]
) -> Dict[str, Dict[str, object]]:
    requested_by_key = {normalize_part_for_match(pn): pn for pn in requested}
    found: Dict[str, Dict[str, object]] = {}
    search_results = response_json.get("SearchResults")
    parts = search_results.get("Parts") if isinstance(search_results, dict) else []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        returned_mpn = str(part.get("ManufacturerPartNumber") or "").strip()
        if not returned_mpn:
            continue
        key = normalize_part_for_match(returned_mpn)
        if key not in requested_by_key:
            continue
        requested_original = requested_by_key[key]
        if normalize_part_for_match(returned_mpn) != normalize_part_for_match(requested_original):
            continue
        current = found.get(requested_original)
        current_url = str(current.get("DataSheetUrl") or "") if current else ""
        new_url = str(part.get("DataSheetUrl") or "")
        if current is None or (not current_url and new_url):
            found[requested_original] = part
    return found


def is_existing_valid_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 100:
        return False
    try:
        with path.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def resolve_api_key(cli_api_key: Optional[str], env_path: Optional[Path] = None) -> str:
    load_dotenv_simple(env_path or Path(".env"))
    api_key = cli_api_key or os.environ.get("MOUSER_API_KEY", "").strip()
    if not api_key:
        api_key = getpass.getpass("Enter MOUSER_API_KEY: ").strip()
    if not api_key:
        raise RuntimeError("MOUSER_API_KEY is required.")
    return api_key
