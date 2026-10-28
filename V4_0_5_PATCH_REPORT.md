# Catalog Automation Agent — Integrated V4.0.5

## Scope and contract

Based on the supplied Integrated V4.0.4 repository and the user-supplied WordPress Add Product / Edit Product / Products list HTML snapshots and the dynamically inspected Rank Math Edit Snippet panel. **The author has not logged in to or changed the production store.**

### Authoritative category

- The user's explicit software UI category selection is the canonical classification for each batch. Fact extraction and semantic audit do not overwrite it.
- Manufacturer differences across legitimate datasheets for one part number are not an error or publisher gate.
- `Edit Category` manages `config/category_registry.json` *locally only*. It never adds/removes WordPress taxonomy terms. Existing WordPress parent and child names must be mapped precisely. Unknown WordPress children block a product before upload; the software never silently picks a different category.
- Form fields: bilingual display name, existing WP parent, existing WP child label, product-title prefix, keyword-density phrase, internal link, optional WP child Term ID. On confirmation additions become selectable across Phase 3, bundle building and Phase 4. Duplicate names/parent-child mappings throw `Category already exists`. Only new custom definitions may be removed; they are marked inactive so previously prepared product records remain interpretable. All additions, deletions and batch applications require confirmations.

### Publisher V4.0.5

1. Actual WooCommerce category inputs are in `#product_catchecklist input[name="tax_input[product_cat][]"]`, including IDs like `#in-product_cat-110-2`, NOT hidden `#in-popular-product_cat-110`. Both parent and child are checked and verified. Optional unknown Term ID resolves strictly from exact WordPress name; missing/ambiguous child fails before uploading images.
2. Fix historic publisher state key conflict `permalink` versus `snippet`. Add `sku` step. Legacy publisher-state JSONs migrate the key on load.
3. Set SKU in WooCommerce Product Data → Inventory field `#_sku` exactly to the part number and verify it.
4. Rank Math edit popup fields from `edit_snippet.txt`: `#rank-math-editor-title`, `#rank-math-editor-permalink`, and `#rank-math-editor-description`. Fully replace `%title% %sep% %sitename%`; verify entered values and close dialog.
5. MOSFET WooCommerce attributes are `Part Number`, optional `پکیج`, optional `Channel Type`, and optional `مشخصات فنی` with `VDS: ... | ID: ...` per the MOSFET content policy. Unsupported individual values are never invented; missing values remain for an admin to fill.
6. Publisher attempts safe read-only site search by PN before creating each product, including already-existing drafts. Exact title or SKU matches cause a skip and preserve WordPress ID, rather than creating duplicates. Local post-ID guard remains. Note: existing incomplete drafts require manual repair.
7. A product with a failed required UI step is *not* saved as a draft; other products continue. After saving a draft, SKU, category, attributes and Rank Math fields are checked again. If a post-ID exists but verification fails, retain the WordPress post-ID and mark `DRAFT_SAVED_WITH_WARNINGS` to prevent duplication.
8. `ALLOW_SITE_WRITE=false` remains the default; drafts only, no clicking Publish.

### MOSFET technical data

- Deterministic facts parser uses the fact-extraction step's structured, part-number-matched `final_facts.json` (based on the resolved datasheet). It recognizes channel type, drain-source voltage, and **continuous** drain current; no substitution of pulsed `IDP`, on-state test current or JFET IDSS.
- The resulting values and source fact IDs are recorded in newly built canonical bundles as `mosfet_specs` and in canonical metadata after bundle building.
- For legacy ready bundles without this new field, Publisher resolves from the existing fact-extraction records. Missing fields are flagged in the Excel report under `MOSFET Specs` as `NEEDS_ADMIN`.
- The system does not currently query Mouser / ALLDATASHEET / Datasheet4U *again* for a missing specification after the existing datasheet facts pass. It uses the existing data-source resolution path. This is a bounded limitation, not an invented claim of external retrieval.

### Safety and migration notes

- Do not copy a stale `runtime_state` folder from an older project over a newer one. Keep WordPress product IDs; they prevent duplicate publishing.
- `2N6660` was already present in the supplied WooCommerce Products snapshot as a WordPress draft, ID `3390`; run-time exact search will skip it if still present rather than duplicate it.
- User-supplied ZIP had an `.env` and `proxies.txt`. They are intentionally excluded from this shareable V4.0.5 ZIP. Copy your own secret values into `.env` and your own proxies into `proxies.txt` locally. Never share credentials in chat or logs.
- The historical `MANIFEST.sha256` should not be reused because source files changed. This ZIP includes an updated file-level manifest.

### Validation performed

- Python compile checks: passed.
- `ALLOW_SITE_WRITE=false python -m pytest -q`: **115 passed**.
- Offline Publisher preflight with the included three canonical ready bundles: all three valid, no WordPress changes.
- HTML/DOM anchors for category, inventory SKU, and Rank Math title/permalink/description were checked against user-supplied HTML captures.
- **Not validated**: real end-to-end Playwright draft-save round trip in WordPress. The runtime did not have a Chromium browser or authenticated access. The first live test should use one explicitly selected test product with write permission after backup, then inspect the resulting draft manually.
