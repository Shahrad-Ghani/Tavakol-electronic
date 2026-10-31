#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tavakol Electronics — Integrated V4 Phase 4 Publisher
=======================================================

Contract:
- Consumes only approved Canonical Bundles from ready_for_upload/<PN>/.
- Creates WooCommerce DRAFTS only; it never clicks Publish.
- Product-specific preflight/step failures do not abort unrelated products.
- Per-product state is stored in runtime_state/publisher/<PN>.json.
- wordpress_product_id / saved state prevents duplicate product creation.

Required publishing flow (new-product path; Repair remains a separate tool):
1) Product title + Phase 3 main HTML.
2) Product image upload/final selection; ALT = exact product title, media title = PN.
3) Datasheet upload when status=completed; NOT_FOUND_CONFIRMED is valid/no upload.
4) Short description and Rank Math snippet from Phase 3 canonical content.
5) Rank Math focus keyword = exact PN.
6) Attributes/SKU, then exact parent + child category from the canonical V4 bundle.
7) Save Draft only. Never update an existing product or click Publish.

Not modified: price, stock quantity, gallery, publish state. SKU is set to exact PN.
ALLOW_SITE_WRITE must explicitly be true for WordPress mutations.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, Locator, TimeoutError as PlaywrightTimeoutError

from core.metadata_v3 import deterministic_product_title, utcnow
from core.category_integrity import assert_bundle_category_consistency
from phase4.publisher_state import PublisherStateStore, sync_publisher_summary_to_metadata
from phase3_fact_extraction.mosfet_specs import resolve_for_product


# ---------------------------------------------------------------------------
# V3 discovers canonical READY bundles dynamically; no hard-coded product scope.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

WP_LOGIN_URL = os.getenv("WP_LOGIN_URL", "https://tavakolelectronic.com/login-page").strip()
WP_USERNAME = os.getenv("WP_USERNAME", "").strip()
WP_PASSWORD = os.getenv("WP_PASSWORD", "")

HEADLESS = os.getenv("HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"}
ALLOW_SITE_WRITE = os.getenv("ALLOW_SITE_WRITE", "false").strip().lower() in {"1", "true", "yes", "on"}

LOGIN_PAGE_WAIT_MS = int(os.getenv("LOGIN_PAGE_WAIT_MS", "3000"))
UI_WAIT_MS = int(os.getenv("UI_WAIT_MS", "900"))
LOCATOR_TIMEOUT_MS = int(os.getenv("LOCATOR_TIMEOUT_MS", "8000"))
UPLOAD_TIMEOUT_MS = int(os.getenv("UPLOAD_TIMEOUT_MS", "60000"))

RUNTIME_ROOT = Path(os.getenv("RUNTIME_ROOT", "")).expanduser() if os.getenv("RUNTIME_ROOT") else ROOT_DIR
LOG_ROOT = RUNTIME_ROOT / "logs" / "phase4"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_DIR = LOG_ROOT / RUN_ID
RUN_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class ProductBundle:
    pn: str
    title: str
    package: Optional[str]
    html_path: Path
    html: str
    short_description_html: str
    image_path: Path
    datasheet_path: Optional[Path]
    datasheet_status: str
    product_json_path: Path
    category_key: str
    category_parent: str
    category_child: str
    category_parent_term_id: int
    category_term_id: int
    slug: str
    seo_title: str
    meta_description: str
    mosfet_specs: Optional[dict[str, Any]] = None
    admin_approved: bool = True
    release_allowed: bool = True


@dataclass
class ProductRunResult:
    pn: str
    status: str
    wordpress_product_id: Optional[str] = None
    wordpress_edit_url: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Logging / state
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"{stamp} | {message}"
    print(line, flush=True)
    with (RUN_DIR / "publisher.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def capture_debug(page: Page, pn: str, name: str = "ERROR") -> None:
    product_dir = RUN_DIR / pn
    product_dir.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(product_dir / f"{name}.png"), full_page=True)
    except Exception:
        pass
    try:
        (product_dir / f"{name}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Canonical Bundle input — V3.0
# ---------------------------------------------------------------------------

def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def first_html_paragraph(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    p = soup.find("p")
    if p is None or not p.get_text(" ", strip=True):
        raise ValueError("Canonical product HTML does not contain a non-empty <p>")
    return str(p).strip()


def build_bundle(bundle_dir: Path) -> ProductBundle:
    """Load one V3 Canonical Bundle. No legacy runtime scanning is allowed here."""
    bundle_dir = Path(bundle_dir).resolve()
    product_json_path = bundle_dir / "product.json"
    if not product_json_path.exists():
        raise FileNotFoundError(f"Canonical product.json missing: {bundle_dir}")
    product = read_json(product_json_path)
    if str(product.get("contract_version") or "") != "4.0":
        raise ValueError("Unsupported canonical bundle contract_version; V4 bundle required")
    pn = str(product.get("part_number") or "").strip()
    if not pn or bundle_dir.name.casefold() != pn.casefold():
        raise ValueError("Canonical bundle directory/part_number mismatch")
    integrity = assert_bundle_category_consistency(product)
    category_block = product.get("category") or {}
    category_key = integrity.key
    expected_title = integrity.expected_title
    title = str(product.get("product_title") or "").strip()
    if title != expected_title:
        raise ValueError(f"Product title must be exactly {expected_title!r}; got {title!r}")
    package = str(product.get("package") or "").strip() or None
    package_status = str(product.get("package_status") or ("resolved" if package else "unresolved")).strip().casefold()
    if package_status == "resolved" and not package:
        raise ValueError("Canonical package_status=resolved but package is empty")
    audit = product.get("audit") or {}
    release = product.get("release") or {}
    if audit.get("status") != "APPROVED" or audit.get("classification") != "FINALIZED" or release.get("allowed") is not True:
        raise ValueError("Bundle is not explicitly approved/released")

    content = product.get("content") or {}
    html_path = bundle_dir / str(content.get("html_file") or "product.html")
    if not html_path.exists():
        raise FileNotFoundError("Canonical product.html is missing")
    html = html_path.read_text(encoding="utf-8")
    if not html.strip():
        raise ValueError("Canonical product HTML is empty")
    short_html = str(content.get("short_description_html") or "").strip()
    if not short_html:
        raise ValueError("Canonical meta/short description is missing")

    image = product.get("image") or {}
    image_path = bundle_dir / str(image.get("file") or "")
    if not image_path.exists() or image_path.stat().st_size <= 0:
        raise FileNotFoundError("Canonical product image is missing/empty")

    ds = product.get("datasheet") or {}
    ds_status = str(ds.get("status") or "pending")
    ds_file = ds.get("file")
    datasheet_path = bundle_dir / str(ds_file) if ds_file else None
    if ds_status == "completed":
        if datasheet_path is None or not datasheet_path.exists() or datasheet_path.stat().st_size <= 0:
            raise FileNotFoundError("Datasheet status=completed but canonical PDF is missing")
    elif ds_status in {"not_found_confirmed", "sales_only_no_datasheet"}:
        if ds_status == "sales_only_no_datasheet" and not bool(ds.get("sales_only_authorized")):
            raise ValueError("Sales-only bundle missing explicit admin authorization")
        datasheet_path = None
    else:
        raise ValueError(f"Datasheet state is not publishable: {ds_status!r}")

    wordpress = product.get("wordpress") or {}
    category = wordpress.get("category") or {}
    parent = str(category.get("parent") or "").strip()
    child = str(category.get("child") or "").strip()
    parent_term_id = int(wordpress.get("category_parent_term_id") or category.get("parent_term_id") or 0)
    term_id = int(wordpress.get("category_term_id") or category.get("term_id") or 0)
    if not parent or not child:
        raise ValueError("Canonical WordPress category mapping is incomplete")
    seo = product.get("seo") or {}
    slug = str(seo.get("permalink") or "").strip()
    seo_title = str(seo.get("seo_title") or "").strip()
    meta_description = str(seo.get("meta_description") or "").strip()
    if not slug or not seo_title or not meta_description:
        raise ValueError("Canonical V4 SEO fields are incomplete")
    if pn.casefold() not in seo_title.casefold():
        raise ValueError(f"Canonical Rank Math SEO title must include the exact Part Number {pn!r}")

    return ProductBundle(
        pn=pn, title=title, package=package, html_path=html_path, html=html,
        short_description_html=short_html, image_path=image_path,
        datasheet_path=datasheet_path, datasheet_status=ds_status,
        product_json_path=product_json_path, category_key=category_key, category_parent=parent, category_child=child,
        category_parent_term_id=parent_term_id, category_term_id=term_id, slug=slug, seo_title=seo_title, meta_description=meta_description,
        mosfet_specs=(product.get("mosfet_specs") or resolve_for_product(RUNTIME_ROOT, pn, category_key)),
    )


def discover_ready_bundles() -> tuple[dict[str, ProductBundle], dict[str, str]]:
    ready = RUNTIME_ROOT / "ready_for_upload"
    ready.mkdir(parents=True, exist_ok=True)
    bundles: dict[str, ProductBundle] = {}
    errors: dict[str, str] = {}
    for folder in sorted((p for p in ready.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.name.casefold()):
        try:
            bundle = build_bundle(folder)
            bundles[bundle.pn] = bundle
            log(f"PREFLIGHT OK | {bundle.pn} | canonical bundle={folder}")
        except Exception as exc:
            errors[folder.name] = f"{type(exc).__name__}: {exc}"
            log(f"PREFLIGHT PRODUCT ERROR | {folder.name} | {errors[folder.name]}")
    return bundles, errors


def global_preflight() -> tuple[dict[str, ProductBundle], dict[str, str]]:
    """Only true global failures abort Phase 4; product failures remain per-product."""
    log(f"Runtime root: {RUNTIME_ROOT}")
    if not RUNTIME_ROOT.exists():
        raise RuntimeError(f"Runtime root does not exist: {RUNTIME_ROOT}")
    ready = RUNTIME_ROOT / "ready_for_upload"
    ready.mkdir(parents=True, exist_ok=True)
    if ALLOW_SITE_WRITE:
        if not WP_LOGIN_URL or not WP_USERNAME or not WP_PASSWORD:
            raise RuntimeError("WordPress credentials/login URL are incomplete")
    bundles, errors = discover_ready_bundles()
    report = {
        "run_id": RUN_ID,
        "runtime_root": str(RUNTIME_ROOT),
        "allow_site_write": ALLOW_SITE_WRITE,
        "ready_products": list(bundles),
        "product_preflight_errors": errors,
    }
    (RUN_DIR / "preflight.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundles, errors


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------

def wait_ms(page: Page, ms: Optional[int] = None) -> None:
    page.wait_for_timeout(ms if ms is not None else UI_WAIT_MS)


def scroll_nudge_down_up(page: Page, reason: str = "locator retry") -> None:
    """Nudge the page down and back up before retrying a missing UI target.

    This is a locator/interaction fallback only: it never clicks hidden controls,
    changes form values, or bypasses WordPress handlers.
    """
    try:
        before = page.evaluate("() => window.scrollY")
        page.evaluate("(pixels) => window.scrollBy(0, pixels)", 360)
        page.wait_for_timeout(180)
        page.evaluate("(pixels) => window.scrollBy(0, -pixels)", 360)
        page.wait_for_timeout(180)
        after = page.evaluate("() => window.scrollY")
        log(f"UI SCROLL RETRY | {reason} | scrollY={before}->{after}")
    except Exception as exc:
        log(f"UI SCROLL RETRY UNAVAILABLE | {reason} | {type(exc).__name__}: {exc}")


def click_with_scroll_retry(
    page: Page,
    locator: Locator,
    action_label: str,
    *,
    timeout_ms: int = 10000,
    already_done=None,
) -> None:
    """Click a resolved locator, nudging the page and retrying actionability once.

    already_done prevents a second click when the first click timed out after its
    handler had already completed (important for row creation and modal actions).
    """
    last_error = None
    for attempt in range(2):
        try:
            locator.scroll_into_view_if_needed(timeout=min(timeout_ms, 4000))
            locator.click(timeout=timeout_ms)
            return
        except Exception as exc:
            last_error = exc
            if already_done is not None:
                try:
                    if already_done():
                        log(f"UI CLICK VERIFIED AFTER TIMEOUT | {action_label}")
                        return
                except Exception:
                    pass
            if attempt == 0:
                scroll_nudge_down_up(page, action_label)
                try:
                    locator.wait_for(state="visible", timeout=min(timeout_ms, 2500))
                except Exception:
                    pass
    raise RuntimeError(
        f"Click failed after scroll retry | action={action_label} | "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


def check_with_scroll_retry(
    page: Page,
    locator: Locator,
    action_label: str,
    *,
    timeout_ms: int = 10000,
) -> None:
    """Check a category checkbox with one safe scroll/retry; checking is idempotent."""
    last_error = None
    for attempt in range(2):
        try:
            locator.scroll_into_view_if_needed(timeout=min(timeout_ms, 4000))
            locator.check(timeout=timeout_ms)
            return
        except Exception as exc:
            last_error = exc
            try:
                if locator.is_checked():
                    return
            except Exception:
                pass
            if attempt == 0:
                scroll_nudge_down_up(page, action_label)
    raise RuntimeError(
        f"Checkbox check failed after scroll retry | action={action_label} | "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


def first_visible(page: Page, selectors: list[str], timeout_ms: Optional[int] = None) -> Locator:
    timeout = timeout_ms if timeout_ms is not None else LOCATOR_TIMEOUT_MS
    deadline = time.monotonic() + timeout / 1000.0
    last_error = None

    def find_now() -> Optional[Locator]:
        nonlocal last_error
        for selector in selectors:
            try:
                loc = page.locator(selector)
                count = loc.count()
                for i in range(min(count, 10)):
                    item = loc.nth(i)
                    if item.is_visible():
                        return item
            except Exception as exc:
                last_error = exc
        return None

    while time.monotonic() < deadline:
        found = find_now()
        if found is not None:
            return found
        page.wait_for_timeout(150)

    # Some WordPress panels and lazy-rendered controls appear only after a
    # small viewport movement. Probe down/up twice, then resolve the same
    # selectors again; never fall back to a hidden or approximate element.
    retry_window = min(1500, max(500, timeout // 4))
    for attempt in range(2):
        scroll_nudge_down_up(page, f"missing selector set {selectors!r} (attempt {attempt + 1})")
        retry_deadline = time.monotonic() + retry_window / 1000.0
        while time.monotonic() < retry_deadline:
            found = find_now()
            if found is not None:
                return found
            page.wait_for_timeout(150)

    raise RuntimeError(
        f"No visible locator found after scroll retries. Tried: {selectors}. "
        f"Last error: {last_error}"
    )


def close_media_modal_if_open(page: Page) -> None:
    for _ in range(4):
        try:
            if page.locator(".media-modal:visible").count() == 0:
                return
        except Exception:
            return

        try:
            btn = first_visible(
                page,
                [
                    ".media-modal:visible button.media-modal-close",
                    ".media-modal:visible .media-modal-close",
                    'button[aria-label="بستن"]:visible',
                    'button[aria-label="Close"]:visible',
                ],
                timeout_ms=2500,
            )
            click_with_scroll_retry(page, btn, "Close WordPress media modal", timeout_ms=3000,
                          already_done=lambda: page.locator(".media-modal:visible").count() == 0)
            wait_ms(page, 350)
        except Exception:
            try:
                page.keyboard.press("Escape")
                wait_ms(page, 350)
            except Exception:
                break

    if page.locator(".media-modal:visible").count():
        raise RuntimeError("Could not close WordPress media modal")


def active_media_file_input(page: Page) -> Locator:
    selectors = [
        '.media-modal:visible .moxie-shim input[type="file"]',
        '.media-modal:visible input[type="file"]',
    ]
    for selector in selectors:
        loc = page.locator(selector)
        if loc.count() > 0:
            # Last plupload input is generally the active shim in WordPress.
            return loc.last
    raise RuntimeError("Active WordPress media file input not found")



def media_upload_error_text(page: Page) -> Optional[str]:
    """Return current visible WordPress media upload error text, if any."""
    try:
        errors = page.locator(".media-modal:visible .upload-errors .upload-error:visible")
        if errors.count():
            return errors.first.inner_text().strip()
    except Exception:
        pass
    return None


def wait_for_media_ready(page: Page, expected_filename: str, timeout_ms: int = UPLOAD_TIMEOUT_MS) -> None:
    """
    Wait until WordPress finishes upload and has an attachment selected/ready.

    Success signals:
      - media select button becomes enabled, AND
      - either an attachment is selected OR attachment-detail fields are visible.

    Any visible upload error aborts immediately.
    """
    deadline = time.time() + timeout_ms / 1000.0
    last_state = ""

    while time.time() < deadline:
        err = media_upload_error_text(page)
        if err:
            raise RuntimeError(
                f"WordPress media upload failed for {expected_filename}: {err}"
            )

        try:
            btn = page.locator(".media-modal:visible .media-button-select:visible")
            button_ready = btn.count() > 0 and btn.first.is_enabled()

            selected_count = page.locator(
                ".media-modal:visible .attachment.selected, "
                ".media-modal:visible .attachment.details"
            ).count()

            details_visible = (
                page.locator(
                    ".media-modal:visible #attachment-details-two-column-title:visible, "
                    ".media-modal:visible #attachment-details-title:visible, "
                    ".media-modal:visible input[data-setting='title']:visible"
                ).count()
                > 0
            )

            if button_ready and (selected_count > 0 or details_visible):
                return

            last_state = (
                f"button_ready={button_ready}, selected={selected_count}, "
                f"details_visible={details_visible}"
            )
        except Exception as exc:
            last_state = f"locator error: {exc}"

        page.wait_for_timeout(250)

    raise RuntimeError(
        f"Media attachment was not ready/selected for {expected_filename}. "
        f"Last state: {last_state}"
    )


def click_media_select_and_verify_closed(
    page: Page,
    expected_filename: str,
    timeout_ms: int = 15000,
) -> None:
    """
    Click the final WordPress media action button ("گزینش..." / "انتخاب")
    and require the modal to close. Uploading alone is NOT considered success.
    """
    wait_for_media_ready(page, expected_filename)

    btn = first_visible(
        page,
        [
            ".media-modal:visible .media-button-select:visible",
            ".media-modal:visible button.media-button-select:visible",
        ],
        timeout_ms=10000,
    )

    if not btn.is_enabled():
        raise RuntimeError(
            f"Final media selection button is still disabled for {expected_filename}"
        )

    click_with_scroll_retry(page, btn, f"Select uploaded media {expected_filename}", timeout_ms=10000,
                          already_done=lambda: page.locator(".media-modal:visible").count() == 0)

    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.media-modal:visible').length === 0",
            timeout=timeout_ms,
        )
    except Exception:
        pass

    wait_ms(page, 600)

    if page.locator(".media-modal:visible").count():
        raise RuntimeError(
            f"Final media selection click did not close the modal for {expected_filename}"
        )


def dispatch_value_events(locator: Locator) -> None:
    """Trigger the events WooCommerce/React-style controls commonly depend on."""
    for event_name in ("input", "change", "blur"):
        try:
            locator.dispatch_event(event_name)
        except Exception:
            pass


def wait_button_enabled(button: Locator, timeout_ms: int = UPLOAD_TIMEOUT_MS) -> None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        try:
            if button.is_visible() and button.is_enabled():
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("Media select button did not become enabled after upload")


def set_editor_html(page: Page, editor_id: str, html: str) -> None:
    """
    Set both TinyMCE (if active) and backing textarea.
    This is required because #content and #excerpt are hidden in Visual mode.
    """
    ok = page.evaluate(
        """([editorId, html]) => {
            let changed = false;
            try {
                if (window.tinymce && tinymce.get(editorId)) {
                    tinymce.get(editorId).setContent(html);
                    tinymce.get(editorId).fire('change');
                    changed = true;
                }
            } catch (e) {}

            const el = document.getElementById(editorId);
            if (el) {
                el.value = html;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                changed = true;
            }
            return changed;
        }""",
        [editor_id, html],
    )
    if not ok:
        raise RuntimeError(f"Editor not found: #{editor_id}")


def login(page: Page) -> None:
    if not WP_LOGIN_URL:
        raise RuntimeError("WP_LOGIN_URL is empty")
    if not WP_USERNAME:
        raise RuntimeError("WP_USERNAME is empty")
    if not WP_PASSWORD:
        raise RuntimeError("WP_PASSWORD is empty")

    log(f"LOGIN | opening {WP_LOGIN_URL}")
    page.goto(WP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    wait_ms(page, LOGIN_PAGE_WAIT_MS)

    username = first_visible(
        page,
        [
            'input[type="text"]:visible',
            'input[type="email"]:visible',
            '#user_login:visible',
        ],
    )
    password = first_visible(
        page,
        [
            'input[type="password"]:visible',
            '#user_pass:visible',
        ],
    )
    submit = first_visible(
        page,
        [
            'input[type="submit"]:visible',
            'button[type="submit"]:visible',
            '#wp-submit:visible',
        ],
    )

    username.fill(WP_USERNAME)
    password.fill(WP_PASSWORD)

    click_with_scroll_retry(
        page, submit, "Submit WordPress login", timeout_ms=15000,
        already_done=lambda: "/wp-admin/" in page.url or page.locator("#adminmenu").count() > 0,
    )

    try:
        page.wait_for_function(
            """() => location.href.includes('/wp-admin/') ||
                     document.querySelector('#adminmenu') !== null ||
                     document.querySelector('#wpadminbar') !== null""",
            timeout=25000,
        )
    except Exception:
        pass

    wait_ms(page, 1200)

    if "/wp-admin/" not in page.url and page.locator("#adminmenu").count() == 0:
        capture_debug(page, "_login", "LOGIN_FAILED")
        raise RuntimeError(f"Login did not reach wp-admin. Current URL: {page.url}")

    log(f"LOGIN OK | {page.url}")


def add_product_url() -> str:
    parsed = urlparse(WP_LOGIN_URL)
    return f"{parsed.scheme}://{parsed.netloc}/wp-admin/post-new.php?post_type=product"


def locate_existing_wordpress_product(page: Page, bundle: ProductBundle) -> tuple[str, str] | None:
    """Read-only WooCommerce admin search before creating a product.

    Matches exact product title OR exact SKU, never fuzzy search-result matches.
    Stops on duplicate matches rather than arbitrarily choosing a product.
    """
    url = WP_LOGIN_URL.split('/login-page')[0].rstrip('/') + '/wp-admin/edit.php?' + urlencode({'post_type':'product','s':bundle.pn})
    page.goto(url, wait_until='domcontentloaded', timeout=35000)
    first_visible(page, ['#posts-filter:visible', '#the-list:visible'], timeout_ms=15000)
    matches = []
    rows = page.locator('#the-list tr[id^="post-"]')
    for idx in range(rows.count()):
        row = rows.nth(idx)
        title = row.locator('a.row-title')
        if title.count() == 0:
            continue
        current_title = title.first.inner_text().strip()
        sku_el = row.locator('.column-sku')
        current_sku = sku_el.first.inner_text().strip() if sku_el.count() else ''
        if current_title.casefold() == bundle.title.casefold() or (current_sku and current_sku.casefold() == bundle.pn.casefold()):
            m = re.search(r'\bpost-(\d+)\b', row.get_attribute('id') or '')
            if m:
                matches.append((m.group(1), title.first.get_attribute('href') or ''))
    if len(matches) > 1:
        raise RuntimeError(f'Multiple WordPress products already match {bundle.pn}: {matches!r}')
    return matches[0] if matches else None


def open_new_product(page: Page, pn: str) -> None:
    close_media_modal_if_open(page)
    url = add_product_url()
    log(f'{pn} | OPEN PRODUCT FORM | {url}')
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=35000)
    except PlaywrightTimeoutError:
        # Navigation can time out even when WordPress has rendered a valid form.
        if page.locator('#title').count() == 0:
            page.goto(url, wait_until='commit', timeout=35000)
    first_visible(page, ['#title:visible'], timeout_ms=15000)
    wait_ms(page, 500)


# ---------------------------------------------------------------------------
# Exact publishing steps
# ---------------------------------------------------------------------------

def upload_product_image(page: Page, bundle: ProductBundle) -> None:
    pn = bundle.pn
    log(f"{pn} | STEP 2 | Product image upload + final selection")

    click_with_scroll_retry(
        page, first_visible(page, ["#set-post-thumbnail:visible"]),
        "Open featured-image media modal",
        already_done=lambda: page.locator(".media-modal:visible").count() > 0,
    )
    first_visible(page, [".media-modal:visible"], timeout_ms=10000)

    try:
        upload_tab = first_visible(
            page,
            [
                'button.media-menu-item:has-text("بارگذاری پرونده‌ها"):visible',
                'button.media-menu-item:has-text("Upload files"):visible',
                '.media-router a:has-text("بارگذاری پرونده‌ها"):visible',
            ],
            timeout_ms=3000,
        )
        click_with_scroll_retry(page, upload_tab, "Open WordPress media upload tab", timeout_ms=5000)
        wait_ms(page, 350)
    except Exception:
        pass

    input_file = active_media_file_input(page)
    input_file.set_input_files(str(bundle.image_path))
    log(f"{pn} | IMAGE FILE SENT | {bundle.image_path}")

    wait_for_media_ready(page, bundle.image_path.name)

    title_input = first_visible(
        page,
        [
            "#attachment-details-two-column-title:visible",
            "#attachment-details-title:visible",
            'input[data-setting="title"]:visible',
        ],
        timeout_ms=UPLOAD_TIMEOUT_MS,
    )
    alt_input = first_visible(
        page,
        [
            "#attachment-details-two-column-alt-text:visible",
            "#attachment-details-alt-text:visible",
            'textarea[data-setting="alt"]:visible',
        ],
        timeout_ms=UPLOAD_TIMEOUT_MS,
    )

    # Contract:
    # ALT = complete product title
    # Media Title = exact Part Number
    alt_input.fill(bundle.title)
    dispatch_value_events(alt_input)

    title_input.fill(pn)
    dispatch_value_events(title_input)

    wait_ms(page, 1200)

    if alt_input.input_value().strip() != bundle.title:
        raise RuntimeError("Image ALT could not be verified before final selection")
    if title_input.input_value().strip() != pn:
        raise RuntimeError("Image media Title could not be verified before final selection")

    # CRITICAL V1.5 FIX: final media selection must actually be clicked.
    click_media_select_and_verify_closed(page, bundle.image_path.name)

    # Verify WordPress featured-image state after modal closes.
    thumb_id = page.locator("#_thumbnail_id")
    if thumb_id.count() == 0 or not thumb_id.first.input_value().strip():
        raise RuntimeError(
            "Product image upload finished, but WordPress _thumbnail_id is empty; "
            "image was not finally selected."
        )

    preview = page.locator("#set-post-thumbnail img")
    preview_found = False
    try:
        preview.first.wait_for(state="visible", timeout=5000)
        preview_found = True
    except Exception:
        # WordPress can commit _thumbnail_id before the preview is repainted.
        # A non-empty _thumbnail_id is the authoritative success criterion.
        preview_found = preview.count() > 0

    if not preview_found:
        log(
            f"{pn} | IMAGE PREVIEW DELAYED/MISSING | "
            f"thumbnail_id={thumb_id.first.input_value()} | "
            "continuing because the attachment ID is valid"
        )

    if preview_found:
        preview_alt = (preview.first.get_attribute("alt") or "").strip()
        if preview_alt and preview_alt != bundle.title:
            log(
                f"{pn} | IMAGE WARNING | preview ALT={preview_alt!r}, "
                f"expected={bundle.title!r}"
            )

    log(
        f"{pn} | STEP 1 OK | thumbnail_id={thumb_id.first.input_value()} | "
        f"preview_found={preview_found} | ALT={bundle.title!r} | media title={pn!r}"
    )


def set_title_and_main_content(page: Page, bundle: ProductBundle) -> None:
    pn = bundle.pn
    log(f"{pn} | STEP 1 | Product title + Phase 3 main content")

    title = first_visible(page, ["#title:visible"])
    title.fill(bundle.title)

    set_editor_html(page, "content", bundle.html)
    wait_ms(page, 500)

    log(f"{pn} | STEP 1 OK | title={bundle.title!r}")


def upload_datasheet(page: Page, bundle: ProductBundle) -> None:
    pn = bundle.pn
    if bundle.datasheet_status in {"not_found_confirmed", "sales_only_no_datasheet"} and bundle.datasheet_path is None:
        log(f"{pn} | STEP 3 OK | Datasheet NOT_FOUND_CONFIRMED; upload not applicable")
        return
    if bundle.datasheet_path is None:
        raise RuntimeError("Datasheet is required by canonical bundle but no PDF path is present")
    log(f"{pn} | STEP 3 | Datasheet upload + final selection")

    add_btn = first_visible(
        page,
        [
            '[data-name="datasheet"] a[data-name="add"]:visible',
            '#acf-group_6a095c60de7a0 a[data-name="add"]:visible',
            'a.acf-button:has-text("افزودن پرونده"):visible',
            'button:has-text("افزودن پرونده"):visible',
        ],
    )
    click_with_scroll_retry(
        page, add_btn, "Open datasheet media modal",
        already_done=lambda: page.locator(".media-modal:visible").count() > 0,
    )
    first_visible(page, [".media-modal:visible"], timeout_ms=10000)

    try:
        upload_tab = first_visible(
            page,
            [
                'button.media-menu-item:has-text("بارگذاری پرونده‌ها"):visible',
                'button.media-menu-item:has-text("Upload files"):visible',
                '.media-router a:has-text("بارگذاری پرونده‌ها"):visible',
            ],
            timeout_ms=3000,
        )
        click_with_scroll_retry(page, upload_tab, "Open WordPress media upload tab", timeout_ms=5000)
        wait_ms(page, 350)
    except Exception:
        pass

    input_file = active_media_file_input(page)
    input_file.set_input_files(str(bundle.datasheet_path))
    log(f"{pn} | PDF FILE SENT | {bundle.datasheet_path}")

    wait_for_media_ready(page, bundle.datasheet_path.name)

    # CRITICAL V1.5 FIX: upload success is not enough; click final selection.
    click_media_select_and_verify_closed(page, bundle.datasheet_path.name)

    acf_id = page.locator('[data-name="datasheet"] input[data-name="id"]')
    if acf_id.count() == 0:
        raise RuntimeError("ACF datasheet attachment ID field was not found")

    attachment_id = acf_id.first.input_value().strip()
    if not attachment_id:
        raise RuntimeError(
            "Datasheet was uploaded but not finally selected: ACF attachment ID is empty"
        )

    # Verify filename shown by ACF after selection.
    filename_link = page.locator('[data-name="datasheet"] [data-name="filename"]')
    shown_name = ""
    if filename_link.count():
        shown_name = filename_link.first.inner_text().strip()

        # WordPress automatically renames duplicate uploads:
        #   TB6600HG.pdf -> TB6600HG-1.pdf -> TB6600HG-2.pdf ...
        # This is valid as long as the ACF attachment ID is populated and the
        # selected filename belongs to the same exact PN.
        expected_stem = bundle.datasheet_path.stem
        expected_suffix = bundle.datasheet_path.suffix
        allowed_name = re.fullmatch(
            rf"{re.escape(expected_stem)}(?:-\d+)?{re.escape(expected_suffix)}",
            shown_name,
            flags=re.IGNORECASE,
        )

        if shown_name and not allowed_name:
            raise RuntimeError(
                f"ACF datasheet filename mismatch: expected {bundle.datasheet_path.name!r} "
                f"or a WordPress duplicate suffix variant, got {shown_name!r}"
            )

        if shown_name and shown_name.casefold() != bundle.datasheet_path.name.casefold():
            log(
                f"{pn} | DATASHEET WORDPRESS RENAME ACCEPTED | "
                f"requested={bundle.datasheet_path.name!r} | selected={shown_name!r}"
            )

    log(
        f"{pn} | STEP 3 OK | datasheet_attachment_id={attachment_id} | "
        f"selected_file={(shown_name or bundle.datasheet_path.name)!r}"
    )


def _attribute_pairs(bundle: ProductBundle) -> tuple[list[tuple[str, str]], list[str]]:
    pairs = [("Part Number", bundle.pn)]
    if str(bundle.package or "").strip():
        pairs.append(("پکیج", str(bundle.package).strip()))
    missing = []
    if bundle.category_key == "mosfet":
        specs = bundle.mosfet_specs or {}
        channel = str((specs.get('channel_type') or {}).get('value') or '').strip()
        if channel:
            pairs.append(('Channel Type', channel))
        else:
            missing.append('channel_type')
        technical = []
        for key, label in (('vds', 'VDS'), ('id_continuous', 'ID')):
            value = str((specs.get(key) or {}).get('value') or '').strip()
            if value:
                technical.append(f'{label}: {value}')
            else:
                missing.append(key)
        if technical:
            pairs.append(('مشخصات فنی', ' | '.join(technical)))
    return pairs, missing


def wait_for_woocommerce_unblocked(page: Page, timeout_ms: int = 20000) -> None:
    """Wait for WooCommerce's transient blockUI overlays to release the form.

    An AJAX overlay can intercept clicks on the attributes panel, Inventory tab,
    or Save Draft. Never force-click through an overlay or manually mutate the DOM.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if page.locator('.blockUI.blockOverlay:visible').count() == 0:
            return
        page.wait_for_timeout(200)
    raise RuntimeError('WooCommerce AJAX/blockUI overlay did not clear before timeout')


def set_attributes(page: Page, bundle: ProductBundle) -> None:
    """Populate WooCommerce attribute inputs without AJAX Save Attributes.

    V4.0.6 operator-approved flow: add rows, fill name/value and rely exclusively
    on the final WordPress Save Draft action. Do not click save_attributes.
    """
    pn = bundle.pn
    log(f"{pn} | STEP 7 | WooCommerce attributes")
    expected, missing = _attribute_pairs(bundle)
    if missing:
        log(f"{pn} | MOSFET SPECS UNRESOLVED | {missing} | admin must complete manually")
    close_media_modal_if_open(page)
    wait_for_woocommerce_unblocked(page)
    click_with_scroll_retry(
        page, first_visible(page, ["li.attribute_options a:visible", 'a[href="#product_attributes"]:visible']),
        "Open WooCommerce Attributes tab",
        already_done=lambda: page.locator("#product_attributes:visible").count() > 0,
    )
    first_visible(page, ["#product_attributes:visible"])
    rows = page.locator("#product_attributes .product_attributes .woocommerce_attribute")
    add_btn = first_visible(page, ["#product_attributes button.add_custom_attribute:visible", "button.add_custom_attribute:visible"])
    while rows.count() < len(expected):
        wait_for_woocommerce_unblocked(page)
        next_count = rows.count() + 1
        click_with_scroll_retry(
            page, add_btn, "Add WooCommerce attribute row", timeout_ms=10000,
            already_done=lambda: rows.count() >= next_count,
        )
        # Row creation may involve asynchronous WooCommerce scripts.
        page.wait_for_function(
            "(n) => document.querySelectorAll('#product_attributes .product_attributes .woocommerce_attribute').length >= n",
            arg=next_count, timeout=15000,
        )
        wait_for_woocommerce_unblocked(page)
    while rows.count() > len(expected):
        wait_for_woocommerce_unblocked(page)
        row = rows.last
        name = row.locator('input.attribute_name').input_value().strip()
        value = row.locator('textarea[name^="attribute_values["]').input_value().strip()
        if name or value:
            raise RuntimeError(f"Unexpected populated attribute row not safe to remove: {name!r}")
        old_count = rows.count()
        click_with_scroll_retry(
            page, row.locator('a.remove_row'), "Remove empty WooCommerce attribute row",
            already_done=lambda: rows.count() < old_count,
        )
        wait_for_woocommerce_unblocked(page)
    for i, (name, value) in enumerate(expected):
        row = rows.nth(i)
        name_input = row.locator('input.attribute_name')
        value_input = row.locator('textarea[name^="attribute_values["]')
        name_input.fill(name)
        dispatch_value_events(name_input)
        value_input.fill(value)
        dispatch_value_events(value_input)
        value_input.press('Tab')
    entered = [(rows.nth(i).locator('input.attribute_name').input_value().strip(),
                rows.nth(i).locator('textarea[name^="attribute_values["]').input_value().strip())
               for i in range(len(expected))]
    if entered != expected:
        raise RuntimeError(f'Attribute form mismatch: {entered!r} vs {expected!r}')
    log(f'{pn} | STEP 7 OK | ATTRIBUTES FILLED (pending final Save Draft) | {expected!r} | missing={missing!r}')


def set_sku(page: Page, bundle: ProductBundle) -> None:
    """Product Data -> Inventory -> SKU = exact part number."""
    log(f"{bundle.pn} | STEP 8 | WooCommerce SKU")
    click_with_scroll_retry(
        page, first_visible(page, ['li.inventory_options a:visible', 'a[href="#inventory_product_data"]:visible']),
        "Open WooCommerce Inventory tab",
        already_done=lambda: page.locator("#_sku:visible").count() > 0,
    )
    sku = first_visible(page, ['#_sku:visible'], timeout_ms=10000)
    previous = sku.input_value().strip()
    if previous and previous.casefold() != bundle.pn.casefold():
        raise RuntimeError(f'Existing SKU differs from PN: {previous!r}')
    sku.fill(bundle.pn)
    dispatch_value_events(sku)
    sku.press('Tab')
    if sku.input_value().strip() != bundle.pn:
        raise RuntimeError('SKU verification failed')
    log(f'{bundle.pn} | STEP 8 OK | SKU SET | {bundle.pn}')


# Legacy V3 example mapping was: قطعات الکترونیکی -> "آی سی". V4 is registry-driven.
def _category_checkbox(page: Page, term_id: int, exact_label: str, *, require_visible: bool = True) -> Locator:
    """Resolve only exact terms from the ALL categories list, never Popular.

    Preflight and post-save verification can safely inspect a hidden checklist;
    setting a category must always use a visible checkbox on the active tab.
    """
    checklist = page.locator('#product_catchecklist')
    if not checklist.count():
        raise RuntimeError('WordPress all-categories checklist missing')
    if term_id:
        cb = checklist.locator(f'input[name="tax_input[product_cat][]"][value="{term_id}"]')
        if cb.count() == 1:
            # CATEGORY_HOTFIX_V2: Rank Math can inject "Make Term Primary"
            # either inside child elements OR directly into label text nodes.
            # Exclude interactive child controls and remove ONLY the known
            # suffix; the exact WordPress term ID/name check stays mandatory.
            raw_label = cb.locator('xpath=..').evaluate(
                r"""(element) => {
                    const cloned = element.cloneNode(true);
                    cloned.querySelectorAll('button, a, [role="button"]').forEach(node => node.remove());
                    return cloned.textContent || '';
                }"""
            )
            label = re.sub(
                r'(?i)\s*(?:Make\s+Term\s+Primary|Remove\s+Primary\s+Term)\s*$',
                '', raw_label
            ).strip()
            label = re.sub(r'\s+', ' ', label)
            log(f'CATEGORY HOTFIX V2 | term={term_id} | observed={raw_label.strip()!r} | normalized={label!r}')
            if re.sub(r'\s+', ' ', label).casefold() != re.sub(r'\s+', ' ', exact_label).casefold():
                raise RuntimeError(f'WordPress term {term_id} name mismatch: {label!r} != {exact_label!r}')
            if require_visible and not cb.is_visible():
                raise RuntimeError(f'WordPress category checkbox is not visible: {exact_label!r}')
            return cb
    matches = checklist.locator('label.selectit').filter(has_text=re.compile(r'^\s*'+re.escape(exact_label)+r'\s*$'))
    if matches.count() != 1:
        raise RuntimeError(f'Existing WordPress category not unique/found: {exact_label!r}')
    cb = matches.first.locator('input[type="checkbox"]')
    if cb.count() != 1 or (require_visible and not cb.is_visible()):
        raise RuntimeError(f'WordPress category checkbox is not visible: {exact_label!r}')
    return cb


def _show_all_product_categories(page: Page) -> None:
    """Switch tabs only when necessary; avoid clicking an off-viewport active tab."""
    checklist = page.locator('#product_catchecklist')
    if not checklist.count():
        raise RuntimeError('WordPress Product Categories checklist is absent')
    if checklist.is_visible():
        return  # Common case: All Categories is already the active panel.

    all_tab = page.locator('#product_cat-tabs a[href="#product_cat-all"]')
    if all_tab.count() == 0:
        raise RuntimeError('All Categories tab not found')
    try:
        click_with_scroll_retry(
            page, all_tab.first, "Open All Product Categories tab", timeout_ms=5000,
            already_done=lambda: checklist.is_visible(),
        )
    except Exception as exc:
        scroll_nudge_down_up(page, "All Product Categories tab handler")
        if not checklist.is_visible():
            raise RuntimeError(
                "All Categories tab handler did not activate after scroll retry"
            ) from exc
    if not checklist.is_visible():
        raise RuntimeError('All Categories checklist did not become visible')


def set_product_category(page: Page, bundle: ProductBundle) -> None:
    pn = bundle.pn
    log(f"{pn} | STEP 9 | WooCommerce parent + child category")
    close_media_modal_if_open(page)
    wait_for_woocommerce_unblocked(page)
    if not page.locator('#product_catdiv').count():
        raise RuntimeError('WooCommerce Product Categories metabox missing')
    _show_all_product_categories(page)
    for term_id, label in ((bundle.category_parent_term_id, bundle.category_parent),
                           (bundle.category_term_id, bundle.category_child)):
        wait_for_woocommerce_unblocked(page)
        checkbox = _category_checkbox(page, term_id, label)
        if not checkbox.is_checked():
            check_with_scroll_retry(page, checkbox, f"Select product category {label}", timeout_ms=12000)
        if not checkbox.is_checked():
            raise RuntimeError(f'Category not checked: {label!r}')
    log(f'{pn} | STEP 9 OK | CATEGORY OK | {bundle.category_parent} -> {bundle.category_child}')


def set_short_description(page: Page, bundle: ProductBundle) -> None:
    pn = bundle.pn
    log(f"{pn} | STEP 4 | Short description = Phase 3 canonical content")

    set_editor_html(page, "excerpt", bundle.short_description_html)
    wait_ms(page, 500)

    log(f"{pn} | STEP 4 OK")


def set_rankmath_snippet(page: Page, bundle: ProductBundle) -> None:
    pn = bundle.pn
    log(f"{pn} | STEP 5 | Rank Math SEO Title + Phase 3 Meta Description + permalink")
    close_media_modal_if_open(page)
    edit_btn = first_visible(page, ["button.rank-math-edit-snippet:visible", 'button:has-text("ویرایش Snippet"):visible'], timeout_ms=10000)
    click_with_scroll_retry(
        page, edit_btn, "Open Rank Math Edit Snippet",
        already_done=lambda: page.locator("#rank-math-editor-title:visible").count() > 0,
    )
    wait_ms(page, 650)

    title = first_visible(page, ["#rank-math-editor-title:visible"], timeout_ms=10000)
    permalink = first_visible(page, ["#rank-math-editor-permalink:visible"], timeout_ms=10000)
    description = first_visible(page, ["#rank-math-editor-description:visible"], timeout_ms=10000)

    # Remove default %title% %sep% %sitename% template before writing canonical V4 title.
    title.press("Control+A"); title.fill(bundle.seo_title); dispatch_value_events(title)
    permalink.press("Control+A"); permalink.fill(bundle.slug); dispatch_value_events(permalink)
    description.press("Control+A"); description.fill(bundle.meta_description); dispatch_value_events(description)
    wait_ms(page, 500)
    if title.input_value().strip() != bundle.seo_title:
        raise RuntimeError("Rank Math SEO title verification failed")
    if permalink.input_value().strip() != bundle.slug:
        raise RuntimeError(f"Rank Math permalink verification failed: {permalink.input_value()!r}")
    if description.input_value().strip() != bundle.meta_description:
        raise RuntimeError("Rank Math meta description verification failed")

    # React modal may not carry the rank-math-modal class on this installation.
    frame = page.locator('.components-modal__frame:visible').filter(has=page.locator('#rank-math-editor-title'))
    if frame.count():
        close_btn = frame.first.locator('button.components-modal__header-button, button[aria-label="بستن"], button[aria-label="Close"]')
        if close_btn.count():
            click_with_scroll_retry(
                page, close_btn.first, "Close Rank Math snippet modal",
                already_done=lambda: page.locator("#rank-math-editor-title:visible").count() == 0,
            )
        else:
            page.keyboard.press('Escape')
    else:
        page.keyboard.press('Escape')
    wait_ms(page, 500)
    if page.locator('#rank-math-editor-title:visible').count():
        raise RuntimeError('Rank Math Edit Snippet modal did not close')
    log(f"{pn} | STEP 5 OK | seo_title={bundle.seo_title!r} | permalink={bundle.slug}")


def set_focus_keyword(page: Page, bundle: ProductBundle) -> None:
    pn = bundle.pn
    log(f"{pn} | STEP 6 | Rank Math focus keyword")

    if page.locator(".components-modal__frame.rank-math-modal:visible").count():
        raise RuntimeError("Rank Math modal is still open before Focus Keyword entry")

    focus = first_visible(
        page,
        [
            ".rank-math-focus-keyword span.tagify__input:visible",
            '.rank-math-focus-keyword [contenteditable="true"]:visible',
            ".rank-math-focus-keyword input:visible",
        ],
        timeout_ms=10000,
    )

    tag_name = focus.evaluate("el => el.tagName.toLowerCase()")

    click_with_scroll_retry(page, focus, "Focus Rank Math keyword field")

    if tag_name == "input":
        focus.fill("")
        focus.fill(pn)
    else:
        # Tagify uses a contenteditable <span>; keyboard input is more reliable
        # than setting innerText programmatically.
        focus.press("Control+A")
        page.keyboard.type(pn, delay=40)

    focus.press("Enter")
    wait_ms(page, 900)

    container = page.locator(".rank-math-focus-keyword")
    container_text = container.inner_text().strip()

    backing_values = []
    inputs = page.locator(".rank-math-focus-keyword input")
    for i in range(inputs.count()):
        try:
            backing_values.append(inputs.nth(i).input_value())
        except Exception:
            pass

    if pn.casefold() not in container_text.casefold() and not any(
        pn.casefold() in (value or "").casefold()
        for value in backing_values
    ):
        raise RuntimeError(
            f"Focus Keyword could not be verified. "
            f"container_text={container_text!r}, backing_values={backing_values!r}"
        )

    log(f"{pn} | STEP 6 OK | focus keyword={pn}")


class DraftVerificationError(RuntimeError):
    def __init__(self, post_id: str, edit_url: str, errors: list[str]):
        self.post_id, self.edit_url, self.errors = post_id, edit_url, errors
        super().__init__('WordPress draft created but post-save verification failed: ' + '; '.join(errors))


def verify_saved_draft(page: Page, bundle: ProductBundle) -> list[str]:
    """Read values back after WordPress returned the product edit page.

    Failures are *warnings with a known post ID*, never permission to recreate.
    """
    errors = []
    def check(label: str, callback):
        try:
            callback()
        except Exception as exc:
            errors.append(f'{label}: {type(exc).__name__}: {exc}')

    def sku_check():
        actual = page.locator('#_sku').input_value().strip()
        if actual != bundle.pn:
            raise ValueError(f'SKU {actual!r} != {bundle.pn!r}')

    def category_check():
        for term, name in ((bundle.category_parent_term_id,bundle.category_parent),
                           (bundle.category_term_id,bundle.category_child)):
            cb = _category_checkbox(page, term, name, require_visible=False)
            if not cb.is_checked():
                raise ValueError(f'Unselected {name!r}')

    def attribute_check():
        expected, _ = _attribute_pairs(bundle)
        rows = page.locator('#product_attributes .product_attributes .woocommerce_attribute')
        found = []
        for idx in range(rows.count()):
            row = rows.nth(idx)
            name = row.locator('input.attribute_name')
            value = row.locator('textarea[name^="attribute_values["]')
            if name.count() and value.count():
                found.append((name.input_value().strip(), value.input_value().strip()))
        for pair in expected:
            if pair not in found:
                raise ValueError(f'Missing WooCommerce attribute: {pair!r}')

    def seo_check():
        edit_btn = first_visible(page, ['button.rank-math-edit-snippet:visible', 'button:has-text("ویرایش Snippet"):visible'], timeout_ms=10000)
        click_with_scroll_retry(
            page, edit_btn, "Open Rank Math snippet for saved-draft verification",
            already_done=lambda: page.locator("#rank-math-editor-title:visible").count() > 0,
        )
        wait_ms(page, 350)
        fields = (('SEO title','#rank-math-editor-title',bundle.seo_title),
                  ('permalink','#rank-math-editor-permalink',bundle.slug),
                  ('meta description','#rank-math-editor-description',bundle.meta_description))
        for label, sel, expected in fields:
            value = first_visible(page,[sel+':visible'],timeout_ms=7000).input_value().strip()
            if value != expected:
                raise ValueError(f'{label} persisted as {value!r}, expected {expected!r}')
        page.keyboard.press('Escape')

    check('SKU', sku_check)
    check('Category', category_check)
    check('Attributes', attribute_check)
    check('Rank Math Snippet', seo_check)
    return errors


def save_draft(page: Page, bundle: ProductBundle) -> tuple[Optional[str], str]:
    pn = bundle.pn
    log(f"{pn} | STEP 10 | Save Draft")

    close_media_modal_if_open(page)
    wait_for_woocommerce_unblocked(page, timeout_ms=30000)
    save_btn = first_visible(page, ["#save-post:visible"])
    if not save_btn.is_enabled():
        raise RuntimeError('WordPress Save Draft button is disabled')
    try:
        save_btn.click(timeout=15000)
    except Exception as exc:
        scroll_nudge_down_up(page, "Save Draft click handler")
        # A click timeout can occur after WordPress has already accepted the save.
        # Never issue a second Save Draft click; first check whether a post ID appears.
        try:
            page.wait_for_function(
                "() => location.href.includes('post.php') && new URL(location.href).searchParams.has('post')",
                timeout=10000,
            )
        except Exception:
            raise RuntimeError(
                f"Save Draft click did not complete after scroll retry; not clicked twice to avoid duplicates: {exc}"
            ) from exc

    # WordPress usually navigates to post.php?post=<ID>&action=edit.
    try:
        page.wait_for_function(
            """() => location.href.includes('post.php') &&
                     new URL(location.href).searchParams.has('post')""",
            timeout=30000,
        )
    except Exception:
        # Some installations remain on page while updating. Give it a final settle.
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

    wait_ms(page, 1200)

    current = page.url
    post_id = None
    try:
        qs = parse_qs(urlparse(current).query)
        if qs.get("post"):
            post_id = qs["post"][0]
    except Exception:
        pass

    # Product ID in post.php is the strongest duplicate-prevention signal.
    # If it exists, immediately treat the Draft save as successful.
    # Title mismatch is logged as a warning instead of throwing after the Draft
    # already exists, because throwing here could create a duplicate on rerun.
    title_value = page.locator("#title").input_value().strip() if page.locator("#title").count() else ""

    if not post_id:
        raise RuntimeError(
            f"Save Draft did not yield a WordPress Product ID. Current URL: {current}"
        )

    if title_value != bundle.title:
        log(
            f"{pn} | SAVE WARNING | Draft has post_id={post_id}, but title verification "
            f"returned {title_value!r} instead of {bundle.title!r}"
        )

    # WordPress already has a draft ID; any verification error must preserve it.
    verification_errors = verify_saved_draft(page, bundle)
    if title_value != bundle.title:
        verification_errors.insert(0, f'Persisted title mismatch: {title_value!r}')
    if verification_errors:
        raise DraftVerificationError(str(post_id), current, verification_errors)
    # Never click #publish.
    log(f"{pn} | STEP 10 OK | DRAFT SAVED & VERIFIED | post_id={post_id} | url={current}")
    return post_id, current



def recover_ui_after_step_error(page: Page, pn: str, step_name: str) -> None:
    """Best-effort cleanup so the next publishing section can continue."""
    try:
        close_media_modal_if_open(page)
    except Exception:
        pass

    try:
        modal = page.locator(".components-modal__frame.rank-math-modal:visible")
        if modal.count():
            close_buttons = page.locator(
                '.components-modal__frame.rank-math-modal button[aria-label="بستن"]:visible, '
                '.components-modal__frame.rank-math-modal button[aria-label="Close"]:visible'
            )
            if close_buttons.count():
                click_with_scroll_retry(
                    page, close_buttons.first, "Close modal during UI recovery",
                    timeout_ms=3000,
                    already_done=lambda: page.locator(".components-modal__frame.rank-math-modal:visible").count() == 0,
                )
    except Exception:
        pass

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    try:
        wait_ms(page, 350)
    except Exception:
        pass

    log(f"{pn} | RECOVERY | after={step_name} | url={page.url}")


def run_resilient_step(
    page: Page,
    bundle: ProductBundle,
    step_key: str,
    step_label: str,
    fn,
    step_errors: dict[str, str],
) -> bool:
    """
    Run one section independently.
    Errors are recorded, logged and recovered from, then the next section runs.
    """
    pn = bundle.pn
    try:
        fn(page, bundle)
        return True
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        step_errors[step_key] = err
        log(f"{pn} | STEP ERROR | {step_label} | {err}")
        log(traceback.format_exc())
        capture_debug(page, pn, f"ERROR_{step_key}")
        recover_ui_after_step_error(page, pn, step_label)
        return False


def publish_one(page: Page, bundle: ProductBundle, store: PublisherStateStore) -> ProductRunResult:
    pn = bundle.pn
    duplicate, prior = store.duplicate_guard(pn)
    if duplicate:
        log(f"{pn} | SKIP | existing WordPress product state | post_id={prior.get('wordpress_product_id')}")
        sync_publisher_summary_to_metadata(RUNTIME_ROOT, pn, prior)
        return ProductRunResult(
            pn=pn,
            status="SKIPPED_ALREADY_SAVED",
            wordpress_product_id=prior.get("wordpress_product_id"),
            wordpress_edit_url=prior.get("wordpress_edit_url"),
        )

    try:
        # Phase 4 creates NEW products only. This exact, read-only lookup is
        # duplicate protection; it never opens or edits an existing post.
        # MOSFET Repair tools remain independent and are not called here.
        existing = locate_existing_wordpress_product(page, bundle)
        if existing:
            wp_id, edit_url = existing
            state = store.mark_existing_site(pn, post_id=wp_id, edit_url=edit_url)
            sync_publisher_summary_to_metadata(RUNTIME_ROOT, pn, state)
            log(f'{pn} | ALREADY EXISTS ON WORDPRESS | post_id={wp_id} | skip to avoid duplicate')
            return ProductRunResult(pn=pn, status='SKIPPED_ALREADY_ON_WORDPRESS', wordpress_product_id=wp_id, wordpress_edit_url=edit_url)
        store.begin(pn)
        open_new_product(page, pn)
        # Read-only preflight BEFORE uploads; missing WordPress category is
        # a hard error, never create a taxonomy term or choose another one.
        _category_checkbox(page, bundle.category_parent_term_id, bundle.category_parent, require_visible=False)
        _category_checkbox(page, bundle.category_term_id, bundle.category_child, require_visible=False)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        log(f"{pn} | FATAL PRODUCT OPEN ERROR | {err}")
        capture_debug(page, pn, "ERROR_OPEN_PRODUCT")
        state = store.mark_failed(pn, err)
        sync_publisher_summary_to_metadata(RUNTIME_ROOT, pn, state)
        return ProductRunResult(pn=pn, status="WP_FAILED", error=err)

    # New-product sequence: title/content -> image/PDF -> Phase 3 short description
    # and SEO snippet -> focus keyword -> attributes/SKU -> exact parent/child category.
    # Existing-product Repair is intentionally separate from this publisher.
    steps = [
        ("title_content", "Product title + Phase 3 main content", set_title_and_main_content),
        ("image", "Product image upload + final selection", upload_product_image),
        ("datasheet", "Datasheet upload/final selection", upload_datasheet),
        ("short_description", "Phase 3 short description", set_short_description),
        ("snippet", "Rank Math SEO title + Phase 3 snippet description", set_rankmath_snippet),
        ("focus_keyword", "Rank Math Focus Keyword", set_focus_keyword),
        ("attributes", "WooCommerce Attributes", set_attributes),
        ("sku", "WooCommerce Inventory SKU", set_sku),
        ("category", "WooCommerce parent + child category", set_product_category),
    ]

    for key, label, fn in steps:
        try:
            fn(page, bundle)
            detail = "not_applicable_no_datasheet" if key == "datasheet" and bundle.datasheet_status in {"not_found_confirmed", "sales_only_no_datasheet"} else None
            store.record_step(pn, key, success=True, detail=detail)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            store.record_step(pn, key, success=False, error=err)
            log(f"{pn} | STEP ERROR | {label} | {err}")
            log(traceback.format_exc())
            capture_debug(page, pn, f"ERROR_{key.upper()}")
            recover_ui_after_step_error(page, pn, label)

    # V4.0.6: attempt the final Save Draft even if an independent UI section
    # failed. This preserves completed form fields instead of abandoning them.
    # Any failed step remains FAILED in PublisherStateStore; finalizing the
    # known WordPress post ID yields DRAFT_SAVED_WITH_WARNINGS, never success.
    # Duplicate Guard / existing-product detection remain entirely unchanged.
    failed_before_save = [k for k, _, _ in steps
                          if (store.load(pn).get('steps', {}).get(k) or {}).get('status') != 'success']
    if failed_before_save:
        log(f'{pn} | SAVE DRAFT WITH WARNINGS | incomplete_steps={failed_before_save!r}')
    capture_debug(page, pn, "BEFORE_SAVE_DRAFT")
    try:
        post_id, edit_url = save_draft(page, bundle)
        store.record_step(pn, "save_draft", success=True, detail={"wordpress_product_id": post_id})
        state = store.finalize_draft(pn, post_id=str(post_id), edit_url=edit_url)
        sync_publisher_summary_to_metadata(RUNTIME_ROOT, pn, state)
        capture_debug(page, pn, "DRAFT_SAVED")
        if state.get("successful"):
            log(f"{pn} | PHASE 4 SUCCESSFUL | post_id={post_id}")
            return ProductRunResult(pn=pn, status="WP_DRAFT_SAVED", wordpress_product_id=str(post_id), wordpress_edit_url=edit_url)
        failed_steps = [k for k, v in (state.get("steps") or {}).items() if v.get("status") != "success"]
        log(f"{pn} | DRAFT SAVED WITH WARNINGS | post_id={post_id} | failed_steps={failed_steps}")
        return ProductRunResult(
            pn=pn, status="WP_DRAFT_SAVED_WITH_WARNINGS",
            wordpress_product_id=str(post_id), wordpress_edit_url=edit_url,
            error=json.dumps({k:v for k,v in (state.get("steps") or {}).items() if v.get("status") != "success"}, ensure_ascii=False),
        )
    except DraftVerificationError as exc:
        store.record_step(pn, "save_draft", success=False, error=str(exc))
        state = store.finalize_draft(pn, post_id=exc.post_id, edit_url=exc.edit_url)
        sync_publisher_summary_to_metadata(RUNTIME_ROOT, pn, state)
        capture_debug(page, pn, "DRAFT_SAVED_VERIFY_FAILED")
        return ProductRunResult(pn=pn, status='WP_DRAFT_SAVED_WITH_WARNINGS',
                                wordpress_product_id=exc.post_id, wordpress_edit_url=exc.edit_url,
                                error=str(exc))
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        store.record_step(pn, "save_draft", success=False, error=err)
        state = store.mark_failed(pn, err)
        sync_publisher_summary_to_metadata(RUNTIME_ROOT, pn, state)
        log(f"{pn} | STEP ERROR | Save Draft | {err}")
        log(traceback.format_exc())
        capture_debug(page, pn, "ERROR_SAVE_DRAFT")
        return ProductRunResult(pn=pn, status="WP_FAILED", error=err)


def main() -> int:
    log("=" * 78)
    log("CATALOG AUTOMATION AGENT — INTEGRATED V4.0.6 PUBLISHER")
    log(f"CATEGORY HOTFIX V2 ACTIVE | loaded_from={Path(__file__).resolve()}")
    log("INPUT: APPROVED CANONICAL BUNDLES ONLY")
    log("FINAL ACTION: SAVE DRAFT ONLY — NEVER PUBLISH")
    log("=" * 78)

    try:
        bundles, preflight_errors = global_preflight()
    except Exception as exc:
        log(f"GLOBAL PREFLIGHT FAILED | {type(exc).__name__}: {exc}")
        return 2

    store = PublisherStateStore(RUNTIME_ROOT)
    for pn, error in preflight_errors.items():
        state = store.mark_failed(pn, f"BUNDLE_PREFLIGHT: {error}")
        sync_publisher_summary_to_metadata(RUNTIME_ROOT, pn, state)

    log(f"PUBLISH PLAN | ready={len(bundles)} | rejected={len(preflight_errors)}")
    for pn, b in bundles.items():
        log(
            f"  {pn} | category={b.category_key} | title={b.title!r} | "
            f"wp_category={b.category_parent!r} -> {b.category_child!r} | "
            f"term_id={b.category_term_id} | slug={b.slug!r} | "
            f"seo_title={b.seo_title!r} | package={b.package!r} | datasheet={b.datasheet_status}"
        )

    if not bundles:
        log("No valid READY canonical bundles found.")
        return 1 if preflight_errors else 0

    if not ALLOW_SITE_WRITE:
        log("DRY RUN COMPLETE | ALLOW_SITE_WRITE=false | no WordPress changes made")
        return 0

    results: list[ProductRunResult] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS)
            context = browser.new_context(viewport={"width": 1440, "height": 950})
            page = context.new_page()
            page.set_default_timeout(LOCATOR_TIMEOUT_MS)
            login(page)
            for pn in sorted(bundles, key=str.casefold):
                try:
                    results.append(publish_one(page, bundles[pn], store))
                except Exception as exc:
                    err = f'{type(exc).__name__}: {exc}'
                    log(f'{pn} | UNEXPECTED PRODUCT FAILURE | {err}')
                    log(traceback.format_exc())
                    state = store.mark_failed(pn, err)
                    sync_publisher_summary_to_metadata(RUNTIME_ROOT, pn, state)
                    results.append(ProductRunResult(pn=pn, status='WP_FAILED', error=err))
            try:
                browser.close()
            except Exception:
                pass
    except Exception as exc:
        log(f"FATAL PUBLISHER ERROR | {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        return 3

    summary = {
        "run_id": RUN_ID,
        "results": [asdict(r) for r in results],
        "preflight_errors": preflight_errors,
    }
    (RUN_DIR / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    success = [r for r in results if r.status == "WP_DRAFT_SAVED"]
    warnings = [r for r in results if r.status == "WP_DRAFT_SAVED_WITH_WARNINGS"]
    skipped = [r for r in results if r.status in {"SKIPPED_ALREADY_SAVED", "SKIPPED_ALREADY_ON_WORDPRESS"}]
    failed = [r for r in results if r.status == "WP_FAILED"]
    log(f"RUN COMPLETE | successful={len(success)} | unsuccessful_with_draft={len(warnings)} | already_saved={len(skipped)} | failed={len(failed)}")
    for r in results:
        log(f"RESULT | {r.pn} | {r.status} | post_id={r.wordpress_product_id} | error={r.error}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
