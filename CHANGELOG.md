## Integrated V4.0.6 — Publisher Save Draft & Failed Datasheet Audit

- WooCommerce attributes: only fill standard fields and dispatch their events; do **not** click `save_attributes` AJAX action. Wait for active AJAX blockUI overlays before changing sections.
- WooCommerce categories: check whether `#product_catchecklist` is already active; avoid redundant out-of-viewport All Categories click. Read-only preflight validates term identity even if tab is hidden; publishing requires visible exact matching parent and child checkboxes.
- Publisher attempts final **Save Draft** even if an earlier independently recoverable step failed, recording `DRAFT_SAVED_WITH_WARNINGS` when an ID was obtained. Post-save SKU/category/attributes/Rank Math checks are retained. Never clicks `#publish`.
- Audit exposes manual PDF attach for `datasheet.status=failed` (including 2SK18). Existing manual attach invalidates facts/Phase 3 and schedules regeneration on next Start.
- `phase4/publisher_state.py` / `duplicate_guard()` logic remains byte-for-byte unchanged from the supplied V4.0.5 repository; existing IDs and runtime state retained.
- Offline regression: 123 passed; five bundled products pass canonical preflight. Live WordPress round-trip **not** tested.

# V4.0.4 Patch — 2026-09-28

- Added deterministic Phase-3 `Intro Header Repair` after Tone Editor and before final SEO/semantic validation.
- Accepts an existing H2 when it contains both `معرفی` and the exact Part Number.
- If missing, inserts the category-aware canonical H2 `معرفی {category_label} {PN}` without any API/model call.
- Repair is idempotent; reruns do not duplicate the introduction heading.
- Final Phase-3 JSON now records `validation.intro_heading` with expected heading, detection result and whether programmatic repair was applied.
- Integrated Phase-3 logs now report `Intro header | status=INSERTED|PRESENT`.
- HTML remains deterministically rendered from the repaired Markdown body.
- Added V4.0.4 regression tests for missing header, existing header, idempotence, HTML rendering and end-to-end Phase-3 export.

# V4.0.3 Patch — 2026-09-28

- Added an immutable Category Integrity gate across Metadata → Phase 3 → Integrated Product → Canonical Bundle → Publisher.
- Added hard `CATEGORY_CONSISTENCY_ERROR` on upstream category disagreement instead of silently falling back to IC.
- Existing READY bundles are validated before reuse; stale category bundles are archived/rebuilt automatically only before a WordPress Product ID exists.
- Canonical Bundle category context is now always derived from the central Category Registry.
- Fixed metadata rename title generation so it uses the selected Category instead of the legacy IC fallback.
- Audit FINALIZED/Approve now require category consistency.
- Publisher preflight validates category key, category-aware title, slug and WooCommerce parent/child/term IDs.
- Publisher plan logs category, WordPress category/term ID, slug and SEO title before opening WordPress.
- Updated Publisher branding to Integrated V4.0.3.
- Fixed Admin original-image lookup to prefer canonical `input_PN/` while retaining legacy `PN_input/` fallback.
- Offline regression suite: 104 passed; compileall and all 12 schemas passed.

# V4.0.2 Patch — 2026-09-28

- Fixed canonical Category persistence: V4 metadata writes no longer delete the `category` block as a legacy alias.
- Hardened integrated-product assembly: `identity.category_context` is reconstructed from the central Category Registry using the canonical category key instead of trusting an optional/stale metadata block.
- This specifically fixes Audit recovery failure: `identity.category_context: 'key' is a required property`.
- Added regression tests for metadata category persistence and registry-backed integrated context.

# V4.0.1 Patch — 2026-09-27

- Fixed strict integrated schema mismatch for `identity.category_context`.
- Fixed false-positive Fact Safety package matching for verified TO-package family claims (e.g. verified `TO-92 3L` safely permits customer text `TO-92`).
- Added bounded targeted Fact Safety repair: previous generated body + exact Fact Safety failures are returned to the writer for correction using verified facts only.
- Added regression tests for package compatibility, strict schema compatibility, explicit repair payload, and end-to-end mocked repair flow.
- Full test suite: 97 passed.

# Integrated V4 — Catalog Automation Agent (2026-09-27)

- Rebranded UI and log panels; removed obsolete Audit footer and stabilized Audit navigation.
- Added persisted Default/Manual mode; V4 Manual mode uses `input_PN/` and filename-authoritative PN.
- Added mandatory per-run Category selector and central JSON Category Registry with real WooCommerce term IDs and category URLs.
- Made product title, density repair, internal linking, slug/permalink, metadata, canonical bundle and Publisher category-aware.
- Added independent SEO Snippet Agent and Rank Math SEO Title/Meta Description writing; Meta Description also feeds WooCommerce Short Description.
- Changed Tone flow so non-safety publishability failures do not prematurely skip Tone Editor.
- Hardened Package normalization to avoid storing prose as canonical package values.
- Added idempotent clickable datasheet banner injection using `assets/banner.png`.
- Preserved unresolved-package publishing behavior and Save-Draft-only Phase 4 policy.
- Added V4 schemas and offline/mock regression tests.

---

# Integrated V3.1

- Minimal patch over Integrated V3.0.
- Unresolved package no longer blocks Canonical Bundle creation or Phase 4.
- Products with unresolved package are published with only the `Part Number` WooCommerce attribute; the `پکیج` attribute is omitted.
- Excel Report keeps `Phase 4 = successful` when all actual Publisher steps succeed, while the `P2 Package` cell remains `unresolved` and is highlighted red.
- No other pipeline behavior was intentionally changed.

---

# Integrated V3.0

- Merged Phase 4 Publisher V1.5.5 behavior into the single Integrated repository.
- Added versioned Metadata Schema V3 and idempotent legacy migration/normalization.
- Removed stale parallel status booleans from the V3 contract; canonical stage states live in their stage blocks.
- Product title is now deterministic (`آی سی <PN>`) and is no longer generated by the Phase 3 LLM.
- Added Phase 2 physical Package extraction from Mouser/Datasheet4U/ALLDATASHEET exact-match evidence.
- Added Phase 3 datasheet Package fallback that never overwrites a valid higher-priority Phase 2 package.
- Added Canonical Bundle contract under `ready_for_upload/<PN>/`; Phase 4 no longer scans legacy runtime folders.
- Added Publisher per-product state, WordPress Product ID anti-duplicate guard, resilient per-step results, and metadata publishing summary.
- Added required WooCommerce category selection: `قطعات الکترونیکی -> آی سی`.
- Added UI Publish/Report controls with idle/audit gating.
- Added daily Excel report with per-stage Phase 1-3 columns and one strict Phase 4 successful/unsuccessful column; rows are green/red by Phase 4 outcome.
- Added approved-legacy bundle preparation before Publisher execution.
- Preserved Draft-only safety: no automatic Publish action.
- Added V3 regression tests, Playwright/OpenPyXL dependencies, secret-safe `.env.example`, and `proxies.example.txt`.

---

## Integrated V2.1.1

- Fixed startup `KeyError: expensive_writer_model`.
- Restored `expensive_writer_model` as a compatibility-only config key pointing to `gpt-5.6-luna`.
- `expensive_writer_max_attempts` remains `0`; no expensive writer path is active.
- Terra remains absent from active code/config.
- Hardened cheap writer config access with a Luna default.

# Integrated V2.1.1

- Removed the expensive model tier from all active processing paths.
- Phase 1 OCR defaults to GPT-5.6 Luna with GPT-5.6 Sol fallback.
- Phase 3 PDF extraction is capped at exactly one GPT-5.6 Luna call over the first up to 5 pages.
- Phase 3 writer uses Luna only; expensive writer escalation is disabled.
- Fixed Admin Audit auto-advance so decisions move strictly forward in the current audit sequence and never jump back to item 1.
- `manual_required` now blocks Phase 3 at orchestrator and adapter layers.
- Added Audit drag-and-drop/Browse manual PDF attachment for missing/manual datasheets.
- Manual PDFs are validated, canonicalized to `datasheets/<PN>.pdf`, Metadata is updated, stale Phase-3 artifacts are archived, and technical SEO is queued for the next Start.

# Tavakol Integrated Phase 1 + Phase 2 + Phase 3 V1.0

## Integrated V1.0
- Added streaming three-phase orchestrator: PN-ready -> immediate Phase 2 -> terminal datasheet decision -> immediate Phase 3.
- Removed orchestrator wait for Phase-2 micro-batch fill; each ready product resolves immediately.
- Added Mouser `ProductAttributes` physical Package/Case extraction with explicit protection against sales `Packaging` confusion.
- Added Package reconciliation against Phase-3 exact-datasheet package facts.
- Removed generated Phase-3 content `.md` artifacts while retaining inline `body_markdown` for validators/rendering.
- Added final `products/PART_NUMBER.json` schema and adapter-ready publishing preview fields.
- Added three-pane Tkinter UI and normalized one-line logs.
- Added startup API/network preflight, automatic network wait/recovery, fatal API auth/credit stop behavior and runtime checkpoints.
- Added merge-safe Phase1/Phase2 metadata writes to prevent concurrent stale-write data loss.
- Added schema validator and integrated regression suite.

# Tavakol_Phase1_Phase2_Integrated_V3.0

## New in V3.0
- OCR upgraded from a nano-only single-pass configuration to a stronger two-stage configuration:
  - primary OCR model: `gpt-5.6-terra`
  - fallback OCR model: `gpt-5.6-sol`
- OCR now uses **dual-image deterministic OCR views** built from both the original and regenerated images.
- Each OCR view now contains:
  - a tight crop of the component
  - an enlarged crop of the central marking region
- OCR requests now use `detail=original` for both images.
- OCR prompt hardened for multi-line PartNumber reconstruction and common confusions such as `B↔8`, `O↔0`, `I/l↔1`, `S↔5`, `Z↔2`, `G↔6`, `C↔G`, `D↔0/O`, `U↔V`, `T↔7`, slash/hyphen/plus confusion.
- OCR now returns structured candidate PartNumbers, critical-character review notes, and explicit model/fallback metadata.
- If the primary and fallback OCR models disagree on an acceptable-looking PartNumber, OCR blocks the PartNumber instead of guessing.

# Integrated V1.0 — Phase 1 + Phase 2

- Merged Phase 2 V4.3-derived production resolver into Phase 1 repository.
- Removed Excel input/reporting from Phase 2.
- Added metadata-driven Phase 2 queue with Mouser micro-batches <=10 and end-run flush.
- Added resume-safe startup discovery and idempotent datasheet states.
- Added exact-PN-only canonical manufacturer/country promotion.
- Preserved Phase 1 OCR manufacturer/country as non-canonical marking evidence.
- Added Phase 2 schema, history, PDF state, ambiguity audit fields, and canonical Phase 1 atomic save callback.
- Added requests + BeautifulSoup dependencies.

# Changelog

## Phase 1 Final V1.5

### Repository integrity / resume fixes
- Fixed resume behavior so a product cannot consume repeated medium fallbacks across later reruns once the configured fallback level is exhausted.
- Updated `.env` validation in `preflight.py` to the real V1.5 `PRIMARY/FALLBACK` settings.
- Added runtime metadata-schema validation on save.
- Updated `metadata_schema.json` enums/fields to match the real V1.5 state and attempt-history structure.
- Improved PartNumber filename safety for Windows-reserved names and trailing dot/space cases.
- Normalized OCR output so `PartNumber` follows `primary_code` when both are returned.

### Layout / logo changes
- Deterministic canvas layout now keeps the component centered on the final canvas.
- If a perfectly centered placement would intrude into the fixed top-left logo zone, the subject is scaled down just enough to clear that zone instead of being shifted off-center.

### Architecture changes
- Switched to **economy-first routing**:
  - first attempt = `gpt-image-2` / `low`
  - fallback = `gpt-image-2` / `medium`
- Precheck no longer decides whether an image goes to the expensive route.
- Expensive fallback now triggers only for **structural mismatches**.

### Validator changes
- Added `body_color_consistency` to the validator schema.
- Fallback trigger is now limited to:
  - `package_geometry_mismatch`
  - `lead_structure_mismatch`
  - `body_color_mismatch`
  - `invented_or_removed_features`
- Markings mismatch, validator uncertainty, and non-critical polish issues no longer trigger fallback.

### OCR changes
- Replaced the generic OCR prompt with a **main commercial part-number extraction** prompt.
- OCR now stores:
  - `visible_lines`
  - `primary_code`
  - `secondary_codes`
  - `notes`

### Layout / logo changes
- Removed model-driven safe-zone behavior.
- Added deterministic logo-space creation in `fit_to_canvas()`.
- Final logo placement remains fixed in one top-left position.

### Prompt pack changes
- New regeneration prompt family: `v5.0-economy-first-reference-lock`
- New validator prompt: `v2-structural-fallback-gate`
- New OCR prompt: `v2.0-main-device-code-extractor`

## Integrated V1.1
- Fixed the Phase-1 stale nested `status` reference bug that could log `FINALIZED` and then incorrectly emit `STOPPED_ITEM` because `status.image_optimized` remained false on disk.
- Merge-safe metadata synchronization now preserves live nested-dict identities; Phase-1 status writes also target the live `data["status"]` mapping directly.
- Added `audit needed/` manual PN-resume workflow. A user may copy an existing `output/*_canvas.png` or `*_regen.png`, rename it to the correct PN, and the next run resumes locally from logo/finalization with zero repeated OpenAI Phase-1 calls.
- Audit files are SHA-256 matched to an existing output candidate to recover the original source reference and prevent arbitrary bypass input.
- Successful audit files move to `audit needed/processed/`; duplicate finalized PNs are never overwritten.
- Orchestrator now has a fast final-checkpoint gate so already-finalized/manual-audited input images do not repeat API work on subsequent runs.

- Added legacy V1.0 finalized-checkpoint recovery: copied `metadata/` + `Final/` items with stale `image_optimized=false` are repaired locally and skipped without repeated Phase-1 API calls. Old absolute Final paths are migrated by canonical basename when `Final/<PN>.webp` exists.

## Integrated V1.2
- Added Admin Audit window to the Tavakol Electronics Tkinter UI; the Audit button is disabled while the pipeline is running and enabled only while stopped.
- Audit view shows original/final-prepared images, PartNumber, datasheet availability/PDF name, SEO score, keyword density/target, word count/target, structure/fact-safety, semantic audit and tone metrics.
- Added green `FINALIZED` and red `AUDIT NEEDED` classifications.
- Added Admin Approve flow that sets `status.admin_approved=true` and creates `ready_for_upload/PART_NUMBER/` bundle.
- Added multi-select Disapprove reasons: wrong PartNumber, image regeneration, wrong datasheet, SEO content regeneration.
- Wrong PartNumber opens an inline `enter the right PN` entry beside the option and disables wrong-datasheet/SEO checkboxes; image regeneration can still be combined.
- Admin PN correction canonicalizes metadata/Final/runtime identity, archives invalid PN-dependent artifacts, reruns Phase 2 and normally Phase 3.
- Added the explicit no-datasheet → no-datasheet exception: when both old and corrected PN resolve to `NOT_FOUND_CONFIRMED`, old sales-only SEO is locally PN-repaired with zero Phase-3 API calls.
- Wrong datasheet invalidates Phase 2, datasheet, fact extraction and SEO; SEO-only invalidates only Phase 3; image-only invalidates only image regeneration/finalization.
- Removed the V1.1 `audit needed/` folder workflow. Manual PN repair now occurs inside Admin Audit UI.
- Added `PN_input/`: filename is trusted PN authority and OCR PartNumber extraction is skipped while the rest of Phase 1 remains active.
- Added `original_imag` metadata evidence for PN_input sources.
- Added `audit_history/` for archived invalidated artifacts and `ready_for_upload/` for Admin-approved publishing bundles.
- Preserved V1.1 stale-status fix and legacy V1.0 final-checkpoint recovery.

## Integrated V2

- Fixed Admin Audit navigation after Approve/Disapprove.
- After a successful decision, the Audit UI automatically advances to the next product not yet reviewed in the current audit session.
- Wrong-PN metadata rename is handled using stable `source_reference`, so auto-advance still works after canonical metadata filename changes.
- After the final product is reviewed, the UI keeps the final item visible and displays `All products reviewed in this audit session` instead of silently wrapping to the first item.
- No Phase 1/2/3 processing architecture, frozen Phase 3 prompts, or scoring policy changed.
