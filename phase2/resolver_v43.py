#!/usr/bin/env python3
"""
Tavakol Electronic — Phase 2 production resolver engine.

Derived from the validated Phase 2 POC V4.3 parser/resolver logic.
This module intentionally contains NO Excel input/reporting and NO product JSON writes.
Product-state orchestration lives in phase2.pipeline / phase2.metadata_state.

Exact Part Number policy remains strict. Manufacturer ambiguity may continue and
is preserved as an audit flag. No Playwright/Selenium is used.
"""
from __future__ import annotations

from .logging_bridge import phase2_log

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from . import core_runtime as core

D4U_SEARCH = "https://datasheet4u.com/search.php"
ALLDATA_SEARCH = "https://www.alldatasheet.com/view.jsp"
ARCHIVE_DELAY = 0.8

SOURCE_EXACT_FOUND = "EXACT_FOUND"
SOURCE_TRUE_NOT_FOUND = "TRUE_NOT_FOUND"
SOURCE_BLOCKED = "BLOCKED"
SOURCE_PARSE_FAILED = "PARSE_FAILED"
SOURCE_REQUEST_FAILED = "REQUEST_FAILED"
SOURCE_HTTP_ERROR = "HTTP_ERROR"
SOURCE_API_FAILED = "API_FAILED"
SOURCE_INVALID_INPUT = "INVALID_INPUT"
SOURCE_NOT_RUN = "NOT_RUN"

MANUFACTURER_ALIASES = {
    "microchip": ["microchip", "microchip technology", "microchip technology inc"],
    "toshiba": ["toshiba", "toshiba semiconductor", "toshiba semiconductor and storage",
                "toshiba electronic devices and storage corporation"],
    "infineon": ["infineon", "infineon technologies", "infineon technologies ag"],
    "st": ["st", "stmicroelectronics", "st microelectronics"],
    "renesas": ["renesas", "renesas electronics", "renesas electronics corporation"],
    "onsemi": ["onsemi", "on semiconductor", "on semiconductor corporation"],
    "fairchild": ["fairchild", "fairchild semiconductor"],
    "ti": ["ti", "texas instruments", "texas instruments incorporated"],
    "nxp": ["nxp", "nxp semiconductors", "philips", "philips semiconductors"],
    "analog_devices": ["analog devices", "analog devices inc", "maxim", "maxim integrated",
                       "linear technology"],
    "mitsubishi": ["mitsubishi", "mitsubishi electric"],
    "fuji": ["fuji", "fuji electric"],
    "sanken": ["sanken", "sanken electric"],
    "allegro": ["allegro", "allegro microsystems"],
    "international_rectifier": ["international rectifier", "ir"],
    "power_integrations": ["power integrations", "power integrations inc"],
    "rohm": ["rohm", "rohm semiconductor"],
    "panasonic": ["panasonic", "panasonic semiconductor"],
    "siemens": ["siemens", "siemens semiconductor", "siemens ag"],
    "telefunken": ["telefunken", "telefunken electronic"],
    "teledyne": ["teledyne", "teledyne technologies", "teledyne technologies incorporated"],
    "thomson": ["thomson", "thomson semiconductors", "thomson csf", "sgs thomson"],
    "signetics": ["signetics", "signetics corporation"],
    "nec": ["nec", "nec electronics"],
    "sanyo": ["sanyo", "sanyo semiconductor"],
    "motorola": ["motorola", "motorola semiconductor"],
    "national_semiconductor": ["national semiconductor", "national semiconductor corporation"],
}

LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "llc", "plc", "ag", "gmbh", "sa", "srl", "bv",
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Candidate:
    source: str
    requested_part_number: str
    matched_part_number: str
    manufacturer: str = ""
    detail_url: str = ""
    pdf_url: str = ""
    note: str = ""
    package_value: str = ""
    package_attribute: str = ""


@dataclass
class SourceDebug:
    part_number: str
    source: str
    state: str = SOURCE_NOT_RUN
    http_status: str = ""
    final_url: str = ""
    exact_evidence: bool = False
    detail_urls_found: int = 0
    candidates_parsed: int = 0
    parse_failures: int = 0
    raw_manufacturers: List[str] = field(default_factory=list)
    canonical_manufacturers: List[str] = field(default_factory=list)
    html_snapshot: str = ""
    note: str = ""


@dataclass
class SearchBundle:
    candidates: List[Candidate]
    debug: SourceDebug


@dataclass
class MouserEntry:
    item: Optional[Dict[str, object]]
    debug: SourceDebug


@dataclass
class Result:
    part_number: str
    status: str
    matched_part_number: str = ""
    manufacturer: str = ""
    identity_source: str = ""
    document_source: str = ""
    datasheet_url: str = ""
    local_file: str = ""
    mouser_part_number: str = ""
    trace: List[str] = field(default_factory=list)
    note: str = ""
    source_debug: List[SourceDebug] = field(default_factory=list)
    ambiguity_flag: str = ""
    ambiguity_source: str = ""
    alternative_manufacturers: List[str] = field(default_factory=list)
    ambiguity_selection_reason: str = ""
    mouser_package: str = ""
    mouser_package_attribute: str = ""
    package_value: str = ""
    package_source: str = ""
    package_attribute: str = ""



_PACKAGE_PAGE_LABELS = {
    "package", "package / case", "package/case", "package case",
    "case / package", "case/package", "case package", "case",
}

def extract_html_package(soup: BeautifulSoup) -> Tuple[str, str]:
    """Best-effort physical package extraction from exact Datasheet4U/ALLDATASHEET detail pages.

    Only explicit package/case labels are accepted. Sales packaging terms are rejected.
    """
    bad = {"reel", "cut tape", "tray", "mousereel", "mouse reel", "bulk", "tube", "tape & reel", "tape and reel"}
    # Structured table rows / definition lists first.
    for row in soup.find_all(["tr", "dl", "p", "div"]):
        cells = row.find_all(["th", "td", "dt", "dd"], recursive=True)
        texts = [c.get_text(" ", strip=True) for c in cells]
        if len(texts) >= 2:
            label = re.sub(r"\s+", " ", texts[0].casefold()).strip(" :")
            if label in _PACKAGE_PAGE_LABELS:
                value = texts[1].strip()
                if value and value.casefold() not in bad and len(value) <= 120:
                    return value, texts[0].strip()
    # Conservative visible-text fallback: label must be explicit and value stays on same line.
    text = soup.get_text("\n", strip=True)
    for pat in (
        r"(?im)^\s*(Package\s*/\s*Case|Package\s+Case|Case\s*/\s*Package|Package|Case)\s*[:|]\s*([^\n\r]{1,120})$",
    ):
        m = re.search(pat, text)
        if m:
            value = m.group(2).strip()
            if value and value.casefold() not in bad:
                return value, m.group(1).strip()
    return "", ""

_PACKAGE_ATTRIBUTE_NAMES = {
    "package / case",
    "package/case",
    "package case",
    "case / package",
    "case/package",
    "case package",
}


def extract_mouser_package(item: Optional[Dict[str, object]]) -> Tuple[str, str]:
    """Extract physical component package from Mouser ProductAttributes.

    Intentionally ignores the top-level `Packaging` field because values such as
    Reel/Cut Tape/MouseReel describe sales packaging, not the IC package/case.
    """
    if not isinstance(item, dict):
        return "", ""
    attrs = item.get("ProductAttributes") or []
    if not isinstance(attrs, list):
        return "", ""
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        name = str(attr.get("AttributeName") or attr.get("Name") or "").strip()
        value = str(attr.get("AttributeValue") or attr.get("Value") or "").strip()
        normalized = re.sub(r"\s+", " ", name.casefold()).strip()
        if normalized in _PACKAGE_ATTRIBUTE_NAMES and value:
            return value, name
    return "", ""


def exact(a: str, b: str) -> bool:
    return core.normalize_part_for_match(a) == core.normalize_part_for_match(b)


def normalize_company_text(value: str) -> str:
    v = unquote(value or "")
    v = v.replace("&", " and ")
    v = re.sub(r"[^a-zA-Z0-9]+", " ", v).strip().casefold()
    return re.sub(r"\s+", " ", v)


def manufacturer_name_variants(value: str) -> List[str]:
    """Return base + bracket manufacturer names, preserving useful aliases.

    ALLDATASHEET commonly emits values like:
        MALLORY [Mallory performance club]
        ALLEGRO [Allegro MicroSystems]
    Both portions are useful and may differ from another source's spelling.
    """
    raw = unquote(value or "").strip()
    if not raw:
        return []
    variants: List[str] = []
    brackets = re.findall(r"\[([^\]]+)\]", raw)
    base = re.sub(r"\[[^\]]*\]", " ", raw).strip()
    for item in [base, *brackets, raw]:
        cleaned = normalize_company_text(item)
        if cleaned and cleaned not in variants:
            variants.append(cleaned)
    return variants


def alias_phrase_matches(cleaned_name: str, cleaned_alias: str) -> bool:
    """Safe alias matching with word/phrase boundaries.

    V4 used `alias in cleaned_name`. That made short aliases dangerous:
    'st' could match inside another company's word, and 'ti' could match inside
    unrelated names. Here an alias must be the full name or a full token/phrase.
    """
    if not cleaned_name or not cleaned_alias:
        return False
    if cleaned_name == cleaned_alias:
        return True
    pattern = r"(?:^|\s)" + re.escape(cleaned_alias) + r"(?:$|\s)"
    return re.search(pattern, cleaned_name) is not None


def strip_legal_suffixes(cleaned: str) -> str:
    tokens = cleaned.split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def canonical_manufacturer(value: str) -> str:
    variants = manufacturer_name_variants(value)
    if not variants:
        return ""

    # Prefer explicit known aliases.
    for variant in variants:
        for canonical, aliases in MANUFACTURER_ALIASES.items():
            for alias in aliases:
                if alias_phrase_matches(variant, normalize_company_text(alias)):
                    return canonical

    # Unknown manufacturer: normalize company legal suffixes, but do not map it
    # to another company by substring.
    normalized = strip_legal_suffixes(variants[0])
    return normalized or variants[0]


def manufacturer_matches(a: str, b: str) -> bool:
    ca, cb = canonical_manufacturer(a), canonical_manufacturer(b)
    return bool(ca and cb and ca == cb)


def compact_visible_part(value: str) -> str:
    # Only used for anchor/result text broken by highlighting tags/spaces.
    return re.sub(r"\s+", "", value or "").strip()


def looks_blocked(status_code: int, html: str) -> bool:
    if status_code in {403, 407, 429}:
        return True
    sample = (html or "")[:50000].casefold()
    blocked_markers = [
        "access to this page has been denied",
        "access denied",
        "request blocked",
        "temporarily blocked",
        "too many requests",
        "just a moment...",
        "challenges.cloudflare.com",
        "cf-chl-",
    ]
    return any(marker in sample for marker in blocked_markers)


def safe_debug_name(pn: str) -> str:
    return core.safe_filename(pn).replace(" ", "_")


class DebugHTMLStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, pn: str, source: str, stage: str, html: str) -> str:
        path = self.root / f"{safe_debug_name(pn)}__{source}__{stage}.html"
        try:
            path.write_text(html or "", encoding="utf-8", errors="ignore")
            return path.as_posix()
        except Exception:
            return ""


class Limiter:
    def __init__(self, seconds: float):
        self.seconds = seconds
        self.last = 0.0

    def wait(self):
        remain = self.seconds - (time.monotonic() - self.last)
        if remain > 0:
            time.sleep(remain)
        self.last = time.monotonic()


def html_title(body: bytes) -> str:
    soup = BeautifulSoup(body[:200000].decode("utf-8", errors="ignore"), "html.parser")
    return soup.title.get_text(" ", strip=True)[:180] if soup.title else ""


def download_pdf(session: core.StickyProxySession, url: str, destination: Path,
                 referer: str = "") -> Tuple[bool, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if core.is_existing_valid_pdf(destination):
        return True, "already_exists"

    temp = destination.with_suffix(destination.suffix + ".part")
    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.7",
    }
    if referer:
        headers["Referer"] = referer

    try:
        r = session.request(
            "GET", url, timeout=(core.CONNECT_TIMEOUT, 75), stream=True,
            allow_redirects=True, headers=headers,
        )
        r.raise_for_status()
        with temp.open("wb") as f:
            for chunk in r.iter_content(65536):
                if chunk:
                    f.write(chunk)
        if not core.is_existing_valid_pdf(temp):
            body = temp.read_bytes() if temp.exists() else b""
            temp.unlink(missing_ok=True)
            return False, (
                f"not_pdf content_type={r.headers.get('Content-Type','')!r} "
                f"final_url={r.url} html_title={html_title(body)!r}"
            )
        os.replace(temp, destination)
        return True, f"pdf_ok final_url={r.url}"
    except Exception as exc:
        temp.unlink(missing_ok=True)
        return False, f"{type(exc).__name__}: {exc}"


def pdf_filename(url: str) -> str:
    name = Path(urlparse(url or "").path).name.strip()
    return name if name.lower().endswith(".pdf") else ""


def official_candidates(manufacturer: str, mouser_url: str) -> List[str]:
    key = canonical_manufacturer(manufacturer)
    filename = pdf_filename(mouser_url)
    if not filename:
        return []

    out: List[str] = []
    if key == "microchip":
        q = quote(filename, safe="._-")
        out += [
            f"https://ww1.microchip.com/downloads/en/DeviceDoc/{q}",
            "https://ww1.microchip.com/downloads/aemDocuments/documents/"
            f"OTH/ProductDocuments/DataSheets/{q}",
        ]
    elif key == "toshiba":
        cleaned = re.sub(r"-\d{5,}(?=\.pdf$)", "", filename, flags=re.I)
        for name in [cleaned, filename]:
            url = "https://toshiba.semicon-storage.com/info/" + quote(name, safe="._-")
            if url not in out:
                out.append(url)
    return out


def try_official(session: core.StickyProxySession, pn: str, manufacturer: str,
                 mouser_url: str, destination: Path) -> Tuple[bool, str, str]:
    candidates = official_candidates(manufacturer, mouser_url)
    if not candidates:
        return False, "", "no_safe_official_candidate_or_adapter"
    notes = []
    for url in candidates:
        phase2_log(f"[OFFICIAL-TRY] {pn} | {manufacturer} | {url}")
        ok, note = download_pdf(session, url, destination)
        if ok:
            return True, url, note
        notes.append(note)
    return False, "", " || ".join(notes)


def mouser_pdf_candidates(url: str) -> List[str]:
    if not url:
        return []
    out: List[str] = []
    def add(x: str):
        if x and x not in out:
            out.append(x)
    add(url)
    p = urlparse(url)
    add(urlunparse((p.scheme or "https", p.netloc, p.path, "", "", "")))
    host = (p.hostname or "").lower()
    if host == "mouser.com" or host.endswith(".mouser.com"):
        add(urlunparse(("https", "www.mouser.com", p.path, "", p.query, "")))
        add(urlunparse(("https", "www.mouser.com", p.path, "", "", "")))
    return out


def try_mouser_pdf(session: core.StickyProxySession, pn: str, url: str,
                   destination: Path, product_url: str = "") -> Tuple[bool, str, str]:
    notes = []
    for candidate in mouser_pdf_candidates(url):
        phase2_log(f"[MOUSER-PDF-TRY] {pn} | {candidate}")
        ok, note = download_pdf(session, candidate, destination, product_url)
        if ok:
            return True, candidate, note
        phase2_log(f"[MOUSER-PDF-FAIL] {pn} | {note}")
        notes.append(note)
    return False, "", " || ".join(notes) if notes else "no_mouser_datasheet_url"


def dedupe_candidates(candidates: Sequence[Candidate]) -> List[Candidate]:
    """Collapse mirror/duplicate URLs from the same manufacturer.

    V4 used detail_url in the de-duplication key, so two mirrors/pages for the
    same exact Part Number and same manufacturer remained separate. V4.1 uses
    exact PN + canonical manufacturer as the main identity key.
    """
    out: List[Candidate] = []
    seen = set()
    for c in candidates:
        manufacturer_key = canonical_manufacturer(c.manufacturer)
        key = (
            core.normalize_part_for_match(c.matched_part_number),
            manufacturer_key or normalize_company_text(c.manufacturer),
        )
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


OFFICIAL_ADAPTER_PRIORITY = {
    "microchip": 0,
    "toshiba": 1,
}


def _candidate_selection_key(candidate: Candidate) -> tuple:
    """Deterministic choice among exact candidates.

    Preference:
    1) manufacturer with an implemented official adapter,
    2) known canonical manufacturer before unknown,
    3) canonical manufacturer name,
    4) raw manufacturer,
    5) stable URL.

    The choice is intentionally deterministic so website result ordering
    cannot silently change the selected datasheet between runs.
    """
    canonical = canonical_manufacturer(candidate.manufacturer)
    return (
        OFFICIAL_ADAPTER_PRIORITY.get(canonical, 999),
        0 if canonical else 1,
        canonical or "~unknown",
        normalize_company_text(candidate.manufacturer),
        candidate.detail_url or candidate.pdf_url or "",
    )


def choose_candidate(candidates: Sequence[Candidate], trusted_manufacturer: str = "") \
        -> Tuple[Optional[Candidate], str, List[str], List[str]]:
    if not candidates:
        return None, "no_exact_candidate", [], []

    unique = dedupe_candidates(candidates)
    raw_mfrs = sorted({
        c.manufacturer.strip()
        for c in unique
        if c.manufacturer.strip()
    })
    canonical_mfrs = sorted({
        canonical_manufacturer(c.manufacturer)
        for c in unique
        if canonical_manufacturer(c.manufacturer)
    })

    if trusted_manufacturer:
        matched = [
            c for c in unique
            if manufacturer_matches(c.manufacturer, trusted_manufacturer)
        ]
        if matched:
            selected = sorted(matched, key=_candidate_selection_key)[0]
            # V1.0 production fix: even when a trusted Mouser manufacturer wins,
            # preserve the fact that other exact-PN manufacturers existed.
            if len(canonical_mfrs) > 1:
                selected_name = (canonical_manufacturer(selected.manufacturer)
                                 or selected.manufacturer or "UNKNOWN")
                alternatives = ",".join(canonical_mfrs)
                return (
                    selected,
                    f"ambiguous_selected_trusted manufacturer={selected_name}; alternatives={alternatives}",
                    raw_mfrs,
                    canonical_mfrs,
                )
            return (
                selected,
                "matched_trusted_manufacturer",
                raw_mfrs,
                canonical_mfrs,
            )

    if len(unique) == 1:
        return unique[0], "single_exact_identity", raw_mfrs, canonical_mfrs

    # Multiple archive pages from the same canonical manufacturer are not
    # considered ambiguous.
    if len(canonical_mfrs) == 1:
        same_mfr = [
            c for c in unique
            if canonical_manufacturer(c.manufacturer) == canonical_mfrs[0]
        ]
        selected = sorted(same_mfr or unique, key=_candidate_selection_key)[0]
        return (
            selected,
            "multiple_pages_single_manufacturer",
            raw_mfrs,
            canonical_mfrs,
        )

    # V4.3 policy:
    # exact Part Number + multiple manufacturers is allowed to continue.
    # One candidate is selected deterministically and the ambiguity remains
    # explicitly recorded in the final report.
    selected = sorted(unique, key=_candidate_selection_key)[0]
    selected_name = (
        canonical_manufacturer(selected.manufacturer)
        or selected.manufacturer
        or "UNKNOWN"
    )

    alternatives = ",".join(canonical_mfrs) if canonical_mfrs else "UNKNOWN_MULTIPLE_PAGES"
    return (
        selected,
        f"ambiguous_selected manufacturer={selected_name}; alternatives={alternatives}",
        raw_mfrs,
        canonical_mfrs,
    )



def alldata_detail_path_part(url: str) -> Tuple[str, str]:
    path = urlparse(url).path
    m = re.search(r"/datasheet-pdf/(?:pdf|view)/\d+/([^/]+)/([^/]+)\.html$", path, re.I)
    if not m:
        return "", ""
    return unquote(m.group(1)).replace("-", " "), unquote(m.group(2))


def d4u_detail_path_part(url: str) -> Tuple[str, str, str]:
    path = urlparse(url).path
    m = re.search(r"/datasheets/([^/]+)/([^/]+)/(\d+)", path, re.I)
    if not m:
        return "", "", ""
    return unquote(m.group(1)).replace("-", " "), unquote(m.group(2)), m.group(3)



UI_JUNK_MANUFACTURERS = {
    "description",
    "manufacturer",
    "datasheet",
    "download",
    "pdf",
    "preview",
    "html",
    "moon",
}


def meta_description_fields(soup: BeautifulSoup) -> Tuple[str, str]:
    """Extract Part # and Manufacturer from a meta description when present."""
    tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    content = str(tag.get("content") or "").strip() if tag else ""

    part = ""
    manufacturer = ""

    m = re.search(
        r"Part\s*(?:#|No\.?|Number)\s*:\s*([A-Za-z0-9+._/#\-]+)",
        content,
        re.I,
    )
    if m:
        part = m.group(1).strip()

    m = re.search(
        r"Manufacturer\s*:\s*([^.;]+(?:\([^)]*\))?)",
        content,
        re.I,
    )
    if m:
        manufacturer = m.group(1).strip()

    return part, manufacturer


def manufacturer_is_ui_junk(value: str) -> bool:
    cleaned = normalize_company_text(value)
    if not cleaned:
        return True
    if cleaned in UI_JUNK_MANUFACTURERS:
        return True
    # Reject values that contain no letters/numbers after normalization.
    return not bool(re.search(r"[a-z0-9]", cleaned))


def choose_structured_manufacturer(
    path_manufacturer: str,
    meta_manufacturer: str,
    visible_manufacturer: str,
) -> str:
    """Prefer structural sources over loose page-text regex.

    Datasheet archive pages contain navigation labels such as "Manufacturer",
    "Description", and theme icons. A loose regex can accidentally capture those.
    The URL manufacturer slug is the strongest archive identity signal.
    """
    for value in [path_manufacturer, meta_manufacturer, visible_manufacturer]:
        value = (value or "").strip()
        if value and not manufacturer_is_ui_junk(value):
            return value
    return ""


def find_exact_visible_part(text: str, pn: str) -> str:
    """Search all visible Part-label occurrences and return only an exact PN.

    This avoids the ALLDATASHEET navigation header:
        Part # / Description / Marking
    being misread as `Part # Description`.
    """
    patterns = [
        r"Part\s*#\s*[:|]?\s*([A-Za-z0-9+._/#\-]+)",
        r"Part\s*No\.?\s*[:|]?\s*([A-Za-z0-9+._/#\-]+)",
        r"Part\s*Number\s*[:|]?\s*([A-Za-z0-9+._/#\-]+)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            candidate = m.group(1).strip()
            if exact(candidate, pn):
                return candidate
    return ""


class Datasheet4U:
    def __init__(self, session: core.StickyProxySession, debug_store: DebugHTMLStore):
        self.session = session
        self.limiter = Limiter(ARCHIVE_DELAY)
        self.debug_store = debug_store

    def search_exact(self, pn: str) -> SearchBundle:
        dbg = SourceDebug(pn, "datasheet4u")
        self.limiter.wait()
        try:
            r = self.session.request(
                "GET", D4U_SEARCH, params={"sWord": pn},
                timeout=(core.CONNECT_TIMEOUT, core.READ_TIMEOUT),
                allow_redirects=True,
                headers={**BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            )
        except Exception as exc:
            dbg.state = SOURCE_REQUEST_FAILED
            dbg.note = f"{type(exc).__name__}: {exc}"
            return SearchBundle([], dbg)

        dbg.http_status = str(r.status_code)
        dbg.final_url = r.url
        if looks_blocked(r.status_code, r.text):
            dbg.state = SOURCE_BLOCKED
            dbg.html_snapshot = self.debug_store.save(pn, "datasheet4u", "search_blocked", r.text)
            dbg.note = f"blocked_or_access_denied title={html_title(r.content)!r}"
            return SearchBundle([], dbg)
        if r.status_code != 200:
            dbg.state = SOURCE_HTTP_ERROR
            dbg.html_snapshot = self.debug_store.save(pn, "datasheet4u", "search_http_error", r.text)
            dbg.note = f"http_{r.status_code}"
            return SearchBundle([], dbg)

        soup = BeautifulSoup(r.text, "html.parser")
        urls: List[str] = []

        def add_url(u: str):
            if u and u not in urls:
                urls.append(u)

        # A direct result/redirect page can itself be a detail page.
        mfr_path, pn_path, _ = d4u_detail_path_part(r.url)
        if pn_path and exact(pn_path, pn):
            dbg.exact_evidence = True
            add_url(r.url)

        for a in soup.find_all("a", href=True):
            absolute = urljoin(r.url, str(a.get("href") or ""))
            mfr, href_pn, _ = d4u_detail_path_part(absolute)
            text = a.get_text(" ", strip=True)
            text_compact = compact_visible_part(text)
            exact_anchor = bool(text_compact and exact(text_compact, pn))
            exact_path = bool(href_pn and exact(href_pn, pn))
            if exact_anchor or exact_path:
                dbg.exact_evidence = True
            if (exact_anchor or exact_path) and "/datasheets/" in urlparse(absolute).path.lower():
                add_url(absolute)

        # Regex fallback catches highlighted/odd anchor layouts.
        escaped = re.escape(pn)
        pat = re.compile(
            r"href=[\"']([^\"']*/datasheets/[^/\"']+/" + escaped + r"/\d+[^\"']*)[\"']",
            re.I,
        )
        for m in pat.finditer(r.text):
            dbg.exact_evidence = True
            add_url(urljoin(r.url, m.group(1)))

        dbg.detail_urls_found = len(urls)
        candidates: List[Candidate] = []
        failures: List[str] = []
        for idx, url in enumerate(urls[:12], 1):
            candidate, failure = self._detail(pn, url, idx)
            if candidate:
                candidates.append(candidate)
            elif failure:
                failures.append(failure)

        dbg.candidates_parsed = len(candidates)
        dbg.parse_failures = len(failures)
        dbg.raw_manufacturers = sorted({c.manufacturer for c in candidates if c.manufacturer})
        dbg.canonical_manufacturers = sorted({canonical_manufacturer(c.manufacturer)
                                              for c in candidates if canonical_manufacturer(c.manufacturer)})

        if candidates:
            dbg.state = SOURCE_EXACT_FOUND
            dbg.note = f"exact_candidates={len(candidates)} detail_urls={len(urls)}"
        elif urls or dbg.exact_evidence:
            dbg.state = SOURCE_PARSE_FAILED
            dbg.html_snapshot = self.debug_store.save(pn, "datasheet4u", "search_parse_failed", r.text)
            dbg.note = "exact evidence existed but no candidate parsed"
            if failures:
                dbg.note += " | " + " | ".join(failures[:4])
        else:
            dbg.state = SOURCE_TRUE_NOT_FOUND
            dbg.note = "search completed; no exact result evidence"

        return SearchBundle(candidates, dbg)

    def _detail(self, pn: str, url: str, index: int) -> Tuple[Optional[Candidate], str]:
        self.limiter.wait()
        try:
            r = self.session.request(
                "GET", url, timeout=(core.CONNECT_TIMEOUT, core.READ_TIMEOUT),
                allow_redirects=True, headers=BROWSER_HEADERS,
            )
        except Exception as exc:
            return None, f"detail#{index} request_failed {type(exc).__name__}: {exc}"
        if looks_blocked(r.status_code, r.text):
            snap = self.debug_store.save(pn, "datasheet4u", f"detail_{index}_blocked", r.text)
            return None, f"detail#{index} blocked http={r.status_code} snapshot={snap}"
        if r.status_code != 200:
            return None, f"detail#{index} http_{r.status_code}"

        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text("\n", strip=True)
        path_mfr, path_pn, detail_id = d4u_detail_path_part(r.url)
        meta_part, meta_mfr = meta_description_fields(soup)

        # Structural URL identity is preferred. We never let a generic
        # navigation label override an exact Part Number encoded in the URL.
        matched = ""
        if path_pn and exact(path_pn, pn):
            matched = path_pn
        elif meta_part and exact(meta_part, pn):
            matched = meta_part
        else:
            matched = find_exact_visible_part(text, pn)

        if not matched:
            snap = self.debug_store.save(
                pn, "datasheet4u", f"detail_{index}_identity_miss", r.text
            )
            return None, (
                f"detail#{index} identity_parse_miss "
                f"path_pn={path_pn!r} meta_part={meta_part!r} snapshot={snap}"
            )

        visible_mfr = ""
        for m in re.finditer(r"Manufacturer\s*:?\s*([^\n\r]+)", text, re.I):
            candidate = m.group(1).strip()
            if not manufacturer_is_ui_junk(candidate):
                visible_mfr = candidate
                break

        # Important V4.2 fix:
        # Datasheet4U detail URLs encode /datasheets/<manufacturer>/<pn>/<id>.
        # Prefer that manufacturer instead of loose visible-page regex.
        manufacturer = choose_structured_manufacturer(
            path_mfr, meta_mfr, visible_mfr
        )

        pdf_url = ""
        for a in soup.find_all("a", href=True):
            absolute = urljoin(r.url, str(a.get("href") or ""))
            p = urlparse(absolute).path.lower()
            if "/pdf/" in p and p.endswith(".pdf"):
                pdf_url = absolute
                break
        if not pdf_url and detail_id:
            pdf_url = f"https://datasheet4u.com/pdf/{detail_id}/{quote(pn, safe='-_.')}.pdf"

        package_value, package_attribute = extract_html_package(soup)
        return Candidate("datasheet4u", pn, matched, manufacturer, r.url, pdf_url,
                         "exact detail-page identity", package_value, package_attribute), ""


class AllDatasheet:
    def __init__(self, session: core.StickyProxySession, debug_store: DebugHTMLStore):
        self.session = session
        self.limiter = Limiter(ARCHIVE_DELAY)
        self.debug_store = debug_store
        self._challenge_until = 0.0

    def search_exact(self, pn: str) -> SearchBundle:
        dbg = SourceDebug(pn, "alldatasheet")
        # Do not hammer a Cloudflare managed challenge on every part number.
        # The provider remains BLOCKED, not FALSE_NOT_FOUND; other sources still run.
        if time.monotonic() < self._challenge_until:
            dbg.state = SOURCE_BLOCKED
            dbg.note = "Cloudflare challenge circuit open; use approved alternative or manual PDF"
            return SearchBundle([], dbg)
        self.limiter.wait()
        try:
            r = self.session.request(
                "GET", ALLDATA_SEARCH,
                params={"Searchword": pn, "sField": "2"},
                timeout=(core.CONNECT_TIMEOUT, core.READ_TIMEOUT),
                allow_redirects=True,
                headers={**BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            )
        except Exception as exc:
            dbg.state = SOURCE_REQUEST_FAILED
            dbg.note = f"{type(exc).__name__}: {exc}"
            return SearchBundle([], dbg)

        dbg.http_status = str(r.status_code)
        dbg.final_url = r.url
        if looks_blocked(r.status_code, r.text):
            self._challenge_until = time.monotonic() + max(60, int(os.getenv("ALLDATASHEET_CHALLENGE_COOLDOWN_SECONDS", "1800")))
            dbg.state = SOURCE_BLOCKED
            dbg.html_snapshot = self.debug_store.save(pn, "alldatasheet", "search_blocked", r.text)
            dbg.note = f"blocked_or_access_denied title={html_title(r.content)!r}"
            return SearchBundle([], dbg)
        if r.status_code != 200:
            dbg.state = SOURCE_HTTP_ERROR
            dbg.html_snapshot = self.debug_store.save(pn, "alldatasheet", "search_http_error", r.text)
            dbg.note = f"http_{r.status_code}"
            return SearchBundle([], dbg)

        soup = BeautifulSoup(r.text, "html.parser")
        urls: List[str] = []

        def add_url(u: str):
            if u and u not in urls:
                urls.append(u)

        # Search may redirect directly to a detail page.
        mfr_path, pn_path = alldata_detail_path_part(r.url)
        if pn_path and exact(pn_path, pn):
            dbg.exact_evidence = True
            add_url(r.url)

        # Strategy 1: exact URL path or exact/compact anchor text.
        for a in soup.find_all("a", href=True):
            absolute = urljoin(r.url, str(a.get("href") or ""))
            path = urlparse(absolute).path
            mfr, path_pn = alldata_detail_path_part(absolute)
            text = a.get_text(" ", strip=True)
            compact = compact_visible_part(text)
            exact_anchor = bool(compact and exact(compact, pn))
            exact_path = bool(path_pn and exact(path_pn, pn))

            if (exact_anchor or exact_path) and "/datasheet-pdf/" in path.lower():
                dbg.exact_evidence = True
                add_url(absolute)

        # Strategy 2: inspect result rows/containers whose visible Part Number
        # is exact, then take a detail-page link from that same row/container.
        for container in soup.find_all(["tr", "li", "div"]):
            visible = container.get_text(" ", strip=True)
            tokens = re.findall(r"[A-Za-z0-9+._/#\-]+", visible)
            if not any(exact(token, pn) for token in tokens):
                continue
            local_links = []
            for a in container.find_all("a", href=True):
                absolute = urljoin(r.url, str(a.get("href") or ""))
                _, path_pn = alldata_detail_path_part(absolute)
                if path_pn and exact(path_pn, pn):
                    local_links.append(absolute)
            if local_links:
                dbg.exact_evidence = True
                for u in local_links:
                    add_url(u)

        # Strategy 3: raw HTML regex for exact detail URL. This catches cases
        # where highlighted markup makes anchor text awkward.
        escaped = re.escape(pn)
        patterns = [
            re.compile(
                r"href=[\"']([^\"']*/datasheet-pdf/(?:pdf|view)/\d+/[^/\"']+/"
                + escaped + r"\.html[^\"']*)[\"']", re.I
            ),
            re.compile(
                r"(/datasheet-pdf/(?:pdf|view)/\d+/[^/\s\"']+/"
                + escaped + r"\.html)", re.I
            ),
        ]
        for pat in patterns:
            for m in pat.finditer(r.text):
                dbg.exact_evidence = True
                add_url(urljoin(r.url, m.group(1)))

        dbg.detail_urls_found = len(urls)
        candidates: List[Candidate] = []
        failures: List[str] = []
        for idx, url in enumerate(urls[:16], 1):
            candidate, failure = self._detail(pn, url, idx)
            if candidate:
                candidates.append(candidate)
            elif failure:
                failures.append(failure)

        dbg.candidates_parsed = len(candidates)
        dbg.parse_failures = len(failures)
        dbg.raw_manufacturers = sorted({c.manufacturer for c in candidates if c.manufacturer})
        dbg.canonical_manufacturers = sorted({canonical_manufacturer(c.manufacturer)
                                              for c in candidates if canonical_manufacturer(c.manufacturer)})

        if candidates:
            dbg.state = SOURCE_EXACT_FOUND
            dbg.note = f"exact_candidates={len(candidates)} detail_urls={len(urls)}"
        elif urls or dbg.exact_evidence:
            dbg.state = SOURCE_PARSE_FAILED
            dbg.html_snapshot = self.debug_store.save(pn, "alldatasheet", "search_parse_failed", r.text)
            dbg.note = "exact result evidence existed but no candidate parsed"
            if failures:
                dbg.note += " | " + " | ".join(failures[:6])
        else:
            dbg.state = SOURCE_TRUE_NOT_FOUND
            dbg.note = "search completed; no exact result evidence"

        return SearchBundle(candidates, dbg)

    def _detail(self, pn: str, url: str, index: int) -> Tuple[Optional[Candidate], str]:
        self.limiter.wait()
        try:
            r = self.session.request(
                "GET", url, timeout=(core.CONNECT_TIMEOUT, core.READ_TIMEOUT),
                allow_redirects=True, headers=BROWSER_HEADERS,
            )
        except Exception as exc:
            return None, f"detail#{index} request_failed {type(exc).__name__}: {exc}"
        if looks_blocked(r.status_code, r.text):
            snap = self.debug_store.save(pn, "alldatasheet", f"detail_{index}_blocked", r.text)
            return None, f"detail#{index} blocked http={r.status_code} snapshot={snap}"
        if r.status_code != 200:
            return None, f"detail#{index} http_{r.status_code}"

        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text("\n", strip=True)
        path_mfr, path_pn = alldata_detail_path_part(r.url)
        meta_part, meta_mfr = meta_description_fields(soup)

        matched = ""
        if path_pn and exact(path_pn, pn):
            matched = path_pn
        elif meta_part and exact(meta_part, pn):
            matched = meta_part
        else:
            matched = find_exact_visible_part(text, pn)

        if not matched:
            snap = self.debug_store.save(
                pn, "alldatasheet", f"detail_{index}_identity_miss", r.text
            )
            return None, (
                f"detail#{index} identity_parse_miss "
                f"path_pn={path_pn!r} meta_part={meta_part!r} snapshot={snap}"
            )

        visible_mfr = ""
        for m in re.finditer(
            r"Manufacturer\s*[:|]?\s*([^\n\r]+)", text, re.I
        ):
            candidate = m.group(1).strip()
            if not manufacturer_is_ui_junk(candidate):
                visible_mfr = candidate
                break

        # Prefer the full meta manufacturer when valid, then the structured
        # URL manufacturer slug, then visible text.
        manufacturer = choose_structured_manufacturer(
            meta_mfr, path_mfr, visible_mfr
        )

        manual = r.url
        manual = re.sub(r"/datasheet-pdf/(?:pdf|view)/", "/datasheet-pdf/download/", manual, flags=re.I)
        package_value, package_attribute = extract_html_package(soup)
        return Candidate(
            "alldatasheet", pn, matched, manufacturer, r.url, manual,
            "exact identity; security-code download not automated", package_value, package_attribute
        ), ""


def mouser_search_all(session: core.StickyProxySession, api_key: str,
                      pns: Sequence[str]) -> Dict[str, MouserEntry]:
    result: Dict[str, MouserEntry] = {}
    valid: List[str] = []
    for pn in pns:
        error = core.validate_part_number_for_mouser(pn)
        if error:
            result[pn] = MouserEntry(
                None,
                SourceDebug(pn, "mouser", SOURCE_INVALID_INPUT, note=error),
            )
        else:
            valid.append(pn)

    limiter = core.SearchRateLimiter()
    batches = list(core.chunks(valid, core.MAX_PARTS_PER_MOUSER_REQUEST))
    for i, batch in enumerate(batches, 1):
        phase2_log(f"[MOUSER-SEARCH] batch={i}/{len(batches)} count={len(batch)}")
        try:
            data = core.mouser_search_batch(session, api_key, batch, limiter)
            found = core.index_exact_mouser_results(batch, data)
            for pn in batch:
                item = found.get(pn)
                if item:
                    manufacturer = str(item.get("Manufacturer") or "").strip()
                    dbg = SourceDebug(
                        pn, "mouser", SOURCE_EXACT_FOUND,
                        candidates_parsed=1,
                        raw_manufacturers=[manufacturer] if manufacturer else [],
                        canonical_manufacturers=[canonical_manufacturer(manufacturer)]
                        if manufacturer else [],
                        note="exact ManufacturerPartNumber returned by Mouser",
                    )
                else:
                    dbg = SourceDebug(
                        pn, "mouser", SOURCE_TRUE_NOT_FOUND,
                        note="Mouser API request succeeded; no exact ManufacturerPartNumber result",
                    )
                result[pn] = MouserEntry(item, dbg)
        except Exception as exc:
            note = f"{type(exc).__name__}: {exc}"
            phase2_log(f"[MOUSER-API-FAIL] batch={i} {note}")
            for pn in batch:
                result[pn] = MouserEntry(
                    None,
                    SourceDebug(pn, "mouser", SOURCE_API_FAILED, note=note),
                )
    return result


def add_selection_debug(dbg: SourceDebug, candidates: Sequence[Candidate], raw: List[str], canonical: List[str], choice: str):
    dbg.raw_manufacturers = raw
    dbg.canonical_manufacturers = canonical
    if choice.startswith("ambiguous_"):
        dbg.note = (dbg.note + " | " if dbg.note else "") + choice


def unresolved_final_status(mouser_dbg: SourceDebug, d4u_dbg: SourceDebug,
                            all_dbg: SourceDebug, identity_found: bool,
                            ambiguous: bool) -> Tuple[str, str]:
    error_states = {
        SOURCE_BLOCKED, SOURCE_PARSE_FAILED, SOURCE_REQUEST_FAILED,
        SOURCE_HTTP_ERROR, SOURCE_API_FAILED,
    }
    source_states = [mouser_dbg.state, d4u_dbg.state, all_dbg.state]
    if any(state in error_states for state in source_states):
        return (
            "UNRESOLVED_SOURCE_ERROR",
            "At least one source could not be conclusively evaluated; do not treat this as true NOT_FOUND.",
        )

    if identity_found:
        return (
            "IDENTITY_FOUND_DATASHEET_UNRESOLVED",
            "Exact product identity was found, but no PDF was successfully resolved/downloaded.",
        )

    if all(state == SOURCE_TRUE_NOT_FOUND for state in source_states):
        return (
            "NOT_FOUND_CONFIRMED",
            "Mouser, Datasheet4U and ALLDATASHEET all completed successfully with no exact result.",
        )

    return (
        "UNRESOLVED",
        "Resolver ended without a document, but evidence is not sufficient for confirmed NOT_FOUND.",
    )


def resolve_one(session: core.StickyProxySession, d4u: Datasheet4U,
                all_data: AllDatasheet, pn: str, destination: Path,
                mouser_entry: MouserEntry) -> Result:
    trace: List[str] = []
    source_debug: List[SourceDebug] = [mouser_entry.debug]
    manufacturer = ""
    identity_source = ""
    matched = ""
    mouser_pn = ""
    mouser_ds = ""
    mouser_product = ""
    identity_found = False
    ambiguous = False
    ambiguity_flag = ""
    ambiguity_source = ""
    alternative_manufacturers: List[str] = []
    ambiguity_selection_reason = ""

    mouser_item = mouser_entry.item
    mouser_package, mouser_package_attribute = extract_mouser_package(mouser_item)
    if mouser_item:
        returned = str(mouser_item.get("ManufacturerPartNumber") or "").strip()
        if returned and exact(returned, pn):
            manufacturer = str(mouser_item.get("Manufacturer") or "").strip()
            identity_source = "mouser"
            matched = returned
            identity_found = True
            mouser_pn = str(mouser_item.get("MouserPartNumber") or "").strip()
            mouser_ds = str(mouser_item.get("DataSheetUrl") or "").strip()
            mouser_product = str(mouser_item.get("ProductDetailUrl") or "").strip()
            trace.append("MOUSER_EXACT")
            phase2_log(f"[MOUSER-EXACT] {pn} | manufacturer={manufacturer}")
        else:
            trace.append("MOUSER_REJECT_NONEXACT")
    else:
        trace.append(f"MOUSER_{mouser_entry.debug.state}")
        phase2_log(f"[MOUSER-{mouser_entry.debug.state}] {pn}")

    # 1) Official manufacturer first.
    if manufacturer:
        ok, url, note = try_official(session, pn, manufacturer, mouser_ds, destination)
        trace.append("OFFICIAL_ATTEMPT")
        if ok:
            trace.append("OFFICIAL_FOUND")
            phase2_log(f"[FOUND-OFFICIAL] {pn}")
            return Result(pn, "DOWNLOADED", matched or pn, manufacturer, identity_source,
                          f"official:{canonical_manufacturer(manufacturer)}", url,
                          destination.as_posix(), mouser_pn, trace, note, source_debug,
                          mouser_package=mouser_package, mouser_package_attribute=mouser_package_attribute,
                          package_value=mouser_package, package_source="mouser" if mouser_package else "",
                          package_attribute=mouser_package_attribute)
        trace.append("OFFICIAL_UNAVAILABLE")

    # 2) Mouser mirror fallback.
    if mouser_ds:
        ok, url, note = try_mouser_pdf(session, pn, mouser_ds, destination, mouser_product)
        trace.append("MOUSER_PDF_ATTEMPT")
        if ok:
            trace.append("MOUSER_PDF_FOUND")
            phase2_log(f"[FOUND-MOUSER] {pn}")
            return Result(pn, "DOWNLOADED", matched or pn, manufacturer, identity_source,
                          "mouser", url, destination.as_posix(), mouser_pn, trace, note,
                          source_debug, mouser_package=mouser_package, mouser_package_attribute=mouser_package_attribute,
                          package_value=mouser_package, package_source="mouser" if mouser_package else "",
                          package_attribute=mouser_package_attribute)
        trace.append("MOUSER_PDF_FAILED")

    # 3) Datasheet4U.
    phase2_log(f"[D4U-SEARCH] {pn}")
    d4u_bundle = d4u.search_exact(pn)
    d4u_dbg = d4u_bundle.debug
    source_debug.append(d4u_dbg)
    trace.append(f"DATASHEET4U_{d4u_dbg.state}")
    d4u_selected, d4u_choice, raw_mfrs, canon_mfrs = choose_candidate(
        d4u_bundle.candidates, manufacturer
    )
    add_selection_debug(d4u_dbg, d4u_bundle.candidates, raw_mfrs, canon_mfrs, d4u_choice)

    if d4u_selected:
        trace.append("DATASHEET4U_EXACT_SELECTED")

        if d4u_choice.startswith("ambiguous_selected"):
            ambiguous = True
            ambiguity_flag = "AMBIGUOUS_EXACT_MATCH"
            ambiguity_source = "datasheet4u"
            alternative_manufacturers = canon_mfrs or raw_mfrs
            ambiguity_selection_reason = d4u_choice
            trace.append("DATASHEET4U_AMBIGUOUS_SELECTED")
            phase2_log(
                f"[D4U-AMBIGUOUS-SELECTED] {pn} | "
                f"selected={d4u_selected.manufacturer} | "
                f"alternatives={alternative_manufacturers}"
            )

        selected_mfr = manufacturer or d4u_selected.manufacturer
        if not identity_source:
            identity_source = "datasheet4u"
            matched = d4u_selected.matched_part_number
            manufacturer = d4u_selected.manufacturer
            identity_found = True
        phase2_log(f"[D4U-EXACT] {pn} | manufacturer={selected_mfr} | choice={d4u_choice}")

        if selected_mfr:
            ok, url, note = try_official(session, pn, selected_mfr, mouser_ds, destination)
            trace.append("OFFICIAL_AFTER_D4U_ATTEMPT")
            if ok:
                trace.append("OFFICIAL_AFTER_D4U_FOUND")
                return Result(
                    pn, "DOWNLOADED", matched or pn, selected_mfr, identity_source,
                    f"official:{canonical_manufacturer(selected_mfr)}", url,
                    destination.as_posix(), mouser_pn, trace, note, source_debug,
                    ambiguity_flag, ambiguity_source, alternative_manufacturers,
                    ambiguity_selection_reason,
                    mouser_package=mouser_package, mouser_package_attribute=mouser_package_attribute,
                    package_value=(mouser_package or d4u_selected.package_value),
                    package_source=("mouser" if mouser_package else ("datasheet4u" if d4u_selected.package_value else "")),
                    package_attribute=(mouser_package_attribute or d4u_selected.package_attribute),
                )
            trace.append("OFFICIAL_AFTER_D4U_UNAVAILABLE")

        if d4u_selected.pdf_url:
            phase2_log(f"[D4U-PDF-TRY] {pn} | {d4u_selected.pdf_url}")
            ok, note = download_pdf(session, d4u_selected.pdf_url, destination,
                                    d4u_selected.detail_url)
            trace.append("DATASHEET4U_PDF_ATTEMPT")
            if ok:
                trace.append("DATASHEET4U_PDF_FOUND")
                phase2_log(f"[FOUND-D4U] {pn}")
                return Result(
                    pn, "DOWNLOADED", matched or pn,
                    manufacturer or d4u_selected.manufacturer,
                    identity_source or "datasheet4u", "datasheet4u",
                    d4u_selected.pdf_url, destination.as_posix(), mouser_pn,
                    trace, note, source_debug,
                    ambiguity_flag, ambiguity_source, alternative_manufacturers,
                    ambiguity_selection_reason,
                    mouser_package=mouser_package, mouser_package_attribute=mouser_package_attribute,
                    package_value=(mouser_package or d4u_selected.package_value),
                    package_source=("mouser" if mouser_package else ("datasheet4u" if d4u_selected.package_value else "")),
                    package_attribute=(mouser_package_attribute or d4u_selected.package_attribute),
                )
            trace.append("DATASHEET4U_PDF_FAILED")
    elif d4u_choice.startswith("ambiguous_"):
        ambiguous = True
        ambiguity_flag = "AMBIGUOUS_EXACT_MATCH"
        ambiguity_source = "datasheet4u"
        alternative_manufacturers = canon_mfrs or raw_mfrs
        ambiguity_selection_reason = d4u_choice
        trace.append("DATASHEET4U_AMBIGUOUS_UNSELECTED")
        phase2_log(f"[D4U-AMBIGUOUS] {pn} | raw={raw_mfrs} canonical={canon_mfrs}")
    else:
        phase2_log(f"[D4U-{d4u_dbg.state}] {pn} | {d4u_dbg.note}")

    # 4) ALLDATASHEET resolver only. No security-code automation.
    phase2_log(f"[ALLDATA-SEARCH] {pn}")
    all_bundle = all_data.search_exact(pn)
    all_dbg = all_bundle.debug
    source_debug.append(all_dbg)
    trace.append(f"ALLDATASHEET_{all_dbg.state}")
    all_selected, all_choice, raw_mfrs, canon_mfrs = choose_candidate(
        all_bundle.candidates, manufacturer
    )
    add_selection_debug(all_dbg, all_bundle.candidates, raw_mfrs, canon_mfrs, all_choice)

    if all_selected:
        trace.append("ALLDATASHEET_EXACT_SELECTED")

        if all_choice.startswith("ambiguous_selected"):
            ambiguous = True
            ambiguity_flag = "AMBIGUOUS_EXACT_MATCH"
            ambiguity_source = (
                ambiguity_source + "+alldatasheet"
                if ambiguity_source else "alldatasheet"
            )
            alternative_manufacturers = list(dict.fromkeys(
                [*alternative_manufacturers, *(canon_mfrs or raw_mfrs)]
            ))
            ambiguity_selection_reason = (
                ambiguity_selection_reason + " | "
                if ambiguity_selection_reason else ""
            ) + all_choice
            trace.append("ALLDATASHEET_AMBIGUOUS_SELECTED")
            phase2_log(
                f"[ALLDATA-AMBIGUOUS-SELECTED] {pn} | "
                f"selected={all_selected.manufacturer} | "
                f"alternatives={alternative_manufacturers}"
            )

        selected_mfr = manufacturer or all_selected.manufacturer
        if not identity_source:
            identity_source = "alldatasheet"
            matched = all_selected.matched_part_number
            manufacturer = all_selected.manufacturer
            identity_found = True
        phase2_log(f"[ALLDATA-EXACT] {pn} | manufacturer={selected_mfr} | choice={all_choice}")
        if selected_mfr:
            ok, url, note = try_official(session, pn, selected_mfr, mouser_ds, destination)
            trace.append("OFFICIAL_AFTER_ALLDATA_ATTEMPT")
            if ok:
                trace.append("OFFICIAL_AFTER_ALLDATA_FOUND")
                return Result(
                    pn, "DOWNLOADED", matched or pn, selected_mfr, identity_source,
                    f"official:{canonical_manufacturer(selected_mfr)}", url,
                    destination.as_posix(), mouser_pn, trace, note, source_debug,
                    ambiguity_flag, ambiguity_source, alternative_manufacturers,
                    ambiguity_selection_reason,
                    mouser_package=mouser_package, mouser_package_attribute=mouser_package_attribute,
                    package_value=(mouser_package or all_selected.package_value),
                    package_source=("mouser" if mouser_package else ("alldatasheet" if all_selected.package_value else "")),
                    package_attribute=(mouser_package_attribute or all_selected.package_attribute),
                )
            trace.append("OFFICIAL_AFTER_ALLDATA_UNAVAILABLE")
        trace.append("ALLDATASHEET_MANUAL_REQUIRED")
        phase2_log(f"[ALLDATA-MANUAL] {pn}")
        return Result(
            pn, "ALLDATASHEET_MANUAL_DOWNLOAD_REQUIRED", matched or pn,
            manufacturer or all_selected.manufacturer, identity_source or "alldatasheet",
            "alldatasheet_manual", all_selected.pdf_url, "", mouser_pn, trace,
            "Exact ALLDATASHEET identity found; security-code submission is intentionally not automated.",
            source_debug,
            ambiguity_flag, ambiguity_source, alternative_manufacturers,
            ambiguity_selection_reason,
            mouser_package=mouser_package, mouser_package_attribute=mouser_package_attribute,
            package_value=(mouser_package or all_selected.package_value),
            package_source=("mouser" if mouser_package else ("alldatasheet" if all_selected.package_value else "")),
            package_attribute=(mouser_package_attribute or all_selected.package_attribute),
        )
    elif all_choice.startswith("ambiguous_"):
        ambiguous = True
        ambiguity_flag = "AMBIGUOUS_EXACT_MATCH"
        ambiguity_source = (
            ambiguity_source + "+alldatasheet"
            if ambiguity_source else "alldatasheet"
        )
        alternative_manufacturers = list(dict.fromkeys(
            [*alternative_manufacturers, *(canon_mfrs or raw_mfrs)]
        ))
        ambiguity_selection_reason = (
            ambiguity_selection_reason + " | "
            if ambiguity_selection_reason else ""
        ) + all_choice
        trace.append("ALLDATASHEET_AMBIGUOUS_UNSELECTED")
        phase2_log(f"[ALLDATA-AMBIGUOUS] {pn} | raw={raw_mfrs} canonical={canon_mfrs}")
    else:
        phase2_log(f"[ALLDATA-{all_dbg.state}] {pn} | {all_dbg.note}")

    status, status_note = unresolved_final_status(
        mouser_entry.debug, d4u_dbg, all_dbg, identity_found, ambiguous
    )
    trace.append(status)
    phase2_log(f"[{status}] {pn}")
    combined_note = (
        status_note
        + f" | Mouser={mouser_entry.debug.state}"
        + f" | Datasheet4U={d4u_dbg.state}"
        + f" | ALLDATASHEET={all_dbg.state}"
    )
    return Result(
        pn, status, matched, manufacturer, identity_source, "", "", "",
        mouser_pn, trace, combined_note, source_debug,
        ambiguity_flag, ambiguity_source, alternative_manufacturers,
        ambiguity_selection_reason,
        mouser_package=mouser_package, mouser_package_attribute=mouser_package_attribute,
        package_value=mouser_package if identity_source == "mouser" else "",
        package_source="mouser" if (identity_source == "mouser" and mouser_package) else "",
        package_attribute=mouser_package_attribute if identity_source == "mouser" else "",
    )


