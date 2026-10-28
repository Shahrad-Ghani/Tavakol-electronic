# Catalog Automation Agent — Integrated V4.0.3 Patch Report

## Purpose
V4.0.3 closes the category-integrity gap discovered during the first live MOSFET publisher run. The run category is now treated as immutable product identity from Metadata through Phase 3, Integrated Product, Canonical Bundle and Publisher.

## Fixes
- Added `core/category_integrity.py` with hard `CATEGORY_CONSISTENCY_ERROR` checks.
- Metadata `category.key` and `product_type` must agree; category is never silently converted to IC by the integrity gate.
- Phase 3 `identity.product_category`, page title, slug and category internal-link policy are checked against Metadata and the registry.
- Integrated Product `identity.category`, `category_context.key`, publishing title and slug are checked against Metadata/Phase 3.
- Canonical Bundle always stores registry-derived category context rather than copying an optional/stale metadata block.
- Existing READY bundles are validated before reuse. If only the bundle category is stale and no WordPress product ID exists, it is archived and rebuilt automatically.
- If upstream Metadata / Phase 3 / Integrated Product disagree, publishing is blocked rather than guessed/repaired.
- Admin Audit classification and Approve now include the category-consistency gate.
- `rename_metadata_to_partnumber()` now creates the title using the selected category instead of the old IC fallback.
- Publisher preflight validates bundle category/title/slug/WordPress term mapping against the central registry.
- Publisher plan logs category key, product title, WooCommerce parent/child, term ID, slug and SEO title before opening WordPress.
- Publisher branding updated to `CATALOG AUTOMATION AGENT — INTEGRATED V4.0.3 PUBLISHER`.
- Admin original-image lookup now checks canonical `input_PN/` before the legacy `PN_input/` fallback.

## Safety boundary
A stale local bundle may be auto-rebuilt only before a WordPress product ID exists. Once a product has a WordPress ID, duplicate-prevention remains authoritative and automatic rebuild is not performed.

## Regression coverage
V4.0.3 adds tests for:
- immutable MOSFET category through Metadata → Phase3 → Integrated Product;
- hard failure on category mismatch;
- strict registry mapping inside Canonical Bundle;
- category-aware title during metadata rename;
- automatic archive/rebuild of a stale IC bundle for a MOSFET product.
