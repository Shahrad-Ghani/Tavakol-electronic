# Integrated V4.0.6 — Patch Report

## Origin and frozen scope

Base: the user's uploaded `integratedv4.0.5.zip`, including product runtime information. Changes were restricted to the operator-approved Publisher and Audit behavior. **Duplicate Guard must not be changed and was not changed**: `phase4/publisher_state.py` is unmodified. No WordPress API call, browser-login or production write occurred while building this patch.

## 1. Publisher: WooCommerce Attributes

Previous behavior: after populating attributes, `set_attributes()` clicked `button.save_attributes`. Site runtime logs showed a `.blockUI.blockOverlay` intercepting that click and a 10-second timeout, aborting the attributes step.

V4.0.6: `set_attributes()` now fills the custom-attribute name/value controls, dispatches value/input events, verifies their contents, and **does not click** `button.save_attributes`. The attributes remain in the form for the final WordPress `#save-post` action. A guarded AJAX-unblock wait is applied around dynamic new-row creation, and before navigation to another panel. The console message says `ATTRIBUTES FILLED (pending final Save Draft)` instead of claiming that the fields have been persisted.

**Limitation:** the saved HTML and tests cannot prove that this WooCommerce installation persists custom attributes when only `#save-post` is used, without its separate attributes AJAX action. After the first live Save Draft, reopen the product and verify attributes. `verify_saved_draft()` retains its actual read-back check and will raise a warning if absent. This follows the operator's explicit instruction, rather than silently restoring the removed AJAX button click.

## 2. Publisher: Category selection

The problem was caused by redundant clicking on `#product_cat-tabs a[href="#product_cat-all"]` even when the "All Categories" panel was already active, producing `outside of viewport` errors. The flow now checks the visibility of `#product_catchecklist` first. It switches tab only when needed, with a native-tab-handler fallback if scrolling/clicking is impossible. Existing term ID, exact-label and parent+child matching are maintained; never selects hidden popular-category checkboxes. Read-only preflight no longer requires the all-categories panel to be visible before checking that the terms exist. Saved-category verification also accepts a hidden tab for read-only inspection.

## 3. Publisher: ensure final Save Draft

Previously `publish_one()` returned `WP_FAILED` before the Save Draft step whenever any previous UI step failed. The new flow **always attempts Save Draft after all step attempts** when the product-opening preflight succeeds. Failed step(s) remain recorded, the program does not report full success, and a returned WordPress post ID is retained in publisher state. Result is `WP_DRAFT_SAVED_WITH_WARNINGS` for a partial draft or post-save verification failure; only complete verified drafts are `WP_DRAFT_SAVED`. If no post ID is returned, the step remains `WP_FAILED` and must be manually inspected before rerunning to avoid duplicates. `#publish` is never used. AJAX overlays are allowed to clear before `#save-post` is clicked, without force-clicking through a blocking overlay.

**Frozen:** `PublisherStateStore.duplicate_guard`, existing WordPress product detection, and the policy to skip existing products are unchanged. Consequently the already-recognized V4.0.5 products may be skipped rather than automatically repaired; manual completion on the website is still needed for those. Keep the original `runtime_state/` and metadata folder.

## 4. Audit: manual datasheet failed status

`run_ui.py` exposes the PDF Browse/Drag-Drop panel for an identified part number when datasheet status is `failed` in addition to `manual_required`, `not_found_confirmed`, and `identity_found_unresolved`. The existing `admin_audit.attach_manual_datasheet()` validates and copies the PDF, marks datasheet as `completed`, invalidates old fact and Phase 3 caches, sets `force_fact_extraction=True`, `force_seo=True`, and queues Phase 3 to rebuild when the user next clicks Start. This does *not* force Phase 1 image recreation if a final image already exists.

## Offline checks

- Full regression: **123 passed** on the packaged source; includes additional tests for no Save Attributes click, active category tab behavior, category tab switching, Save Draft after an individual error, draft-only action, preservation of post ID/warning status, failed-datasheet attach and `duplicate_guard` source fingerprint.
- Package compile/import: completed without syntax errors.
- Five supplied ready-for-upload bundles `2N4093`, `2N6660`, `2N7000`, `2SJ380`, `2SJ412` passed offline canonical Publisher preflight. `2SK18` still needs a user-supplied PDF before the Phase 3 path.
- **Live browser/site publishing was not run**; do not confuse mocked UI/DOM tests with verification of WooCommerce persistence.

## How to use in Windows

1. Back up the complete V4.0.5 folder (including `metadata/`, `runtime_state/`, `Final/`, `input_PN/`, `datasheets/`, and `ready_for_upload/`). Extract the new ZIP into a separate folder, keeping the single project root.
2. Copy your own `.env` and `proxies.txt` **locally** from the backed-up project if needed; these contain secrets and are not included in the distributed ZIP. Do not overwrite the new source files with the old versions.
3. Run `python run_ui.py`; in Audit on `2SK18` you should see a `DATASHEET SEARCH FAILED` PDF area. Choose the exact 2SK18 datasheet and click Start to regenerate the dependent facts and SEO. Audit approval is still required per the pipeline rules.
4. On an explicitly controlled new test product only, allow Publisher to create a draft; reopen WordPress and check saved `Part Number`, `پکیج`, `Channel Type`, `مشخصات فنی`, SKU, category, SEO Title, description, selected image and PDF attachment. Inspect the `logs/phase4` and `runtime_state/publisher` warning statuses before processing a larger batch.
5. Because Duplicate Guard is unchanged, **do not** expect already-recognized V4.0.5 WordPress products to be republished; complete their missing fields manually in the existing product.

### Safety

No price/stock or publish action was changed. Production site changes are controlled by existing `ALLOW_SITE_WRITE` setting and only `Save Draft` is clicked.
