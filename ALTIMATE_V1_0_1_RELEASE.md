# Catalog Automation Agent — Altimate V1.0.1 Recovery Hotfix

## What this release fixes

This is a **full independent repository**, based on Altimate V1.0.0. It is not a drop-in script patch for V4.0.6.1.

1. Phase 2 **does not re-search** when it finds a confirmed local PDF, an explicit Sales-only admin authorization or an already approved product pending reconciliation. It checks eligibility *before* resetting the datasheet state to `searching`.
2. Phase 2's metadata writer **does not accept stale web results** over a newer, currently valid PDF or Admin decision. A historical human decision with a surviving PDF is also protected until recovery is performed. Explicit disapprovals invalidating datasheet identity are handled using the existing Audit workflow.
3. `recover_datasheet_authority.py` can restore overwritten admin authority from the existing history, **only for items currently showing `web_error`**. It verifies PDF readability for manually attached files. Dry-run is the default; Apply backs up every changed metadata file under `audit_history/Altimate_V1_0_1_recovery_<UTC>/` before atomic replacement. It never clicks Approve, never publishes, never modifies SEO content, and never invents a PDF. Unverified cases remain for manual review.
4. Audit adds **PN search** and filters `Rejected Images`, `Missing Final`, `Needs Audit`, `Datasheet web_error`. Rejected images can be opened by PN even when candidates are missing; to accept, their recorded actual `output/<PN>_canvas.png` or `_regen.png` image must be restored and manually inspected. No auto-approve.
5. Image regeneration converts WebP/other unsupported input formats into a temporary PNG before uploading to OpenAI Images API, fixing `application/octet-stream` errors for `OSG65R130PT3Z.webp` without altering the original.
6. Manual Mode can resume existing checkpoints with empty `input_PN` and `PN_input` directories.
7. ALLDATASHEET Cloudflare challenge is explicitly detected (including HTTP 200 challenge pages). A challenge opens a 30-minute configurable circuit breaker, avoiding hundreds of useless requests. Mouser and Datasheet4U remain available; `BLOCKED` is not treated as `NOT_FOUND`. **This does not bypass Cloudflare**; actual access requires the website to allow the requests or another authorized PDF source.

**Frozen features:** Duplicate Guard, Publisher and Save Draft behavior were not modified. Phase1/Phase3 worker counts default to 10/10 and Phase2 1; all other decisions from V1.0.0 remain.

## Installation and recovery on Windows

1. Close Altimate V1.0.0 and make a backup of its folder. Do not start Publisher.
2. Extract the new ZIP in a **new folder**, not on top of V1.0.0.
3. From CMD **inside the new Altimate V1.0.1 folder**:

```cmd
python upgrade_from_altimate_v100.py --source "C:\PATH\TO\ACTIVE\Catalog_Automation_Agent_Altimate_V1_0_0" --dry-run
python upgrade_from_altimate_v100.py --source "C:\PATH\TO\ACTIVE\Catalog_Automation_Agent_Altimate_V1_0_0" --apply
```

This copies live `metadata`, `runtime_state`, `Final`, `datasheets`, `phase3_outputs`, `products`, `work`, `output`, `input`, `input_PN`, `PN_input`, `ready_for_upload`, `audit_history`, `logs`, `debug_html`, `.env` and `proxies.txt`, if present. **It never copies old code or modifies the source installation.** It may take several minutes because it compares content hashes, especially with many PDFs/images.

4. **Before starting the application**, review proposed metadata restoration:

```cmd
python recover_datasheet_authority.py --dry-run --report recovery_preview.csv
```

Ensure the six confirmed local PDFs exist and the `RESTORE_MANUAL_PDF` actions are correct. Additional `RESTORE_SALES_ONLY` actions may include previously approved products if their authorization history is present. `MANUAL_REVIEW` is not an automatic failure; it includes unproven web errors.

5. After checking the preview:

```cmd
python recover_datasheet_authority.py --apply --report recovery_applied.csv
```

Each changed metadata JSON receives a backup copy, and the recovery runs only on current `web_error` records with a traceable admin decision. Re-running the script is safe: already restored records are skipped. **The actual PDFs' internal PN/variant text still requires human verification**; the script verifies PDF structure and historical admin attachment events, not semantic correctness.

6. Install dependencies and run focused tests:

```cmd
python -m pip install -r requirements.txt
python -m pytest -q tests_altimate_v100 tests_altimate_v101 tests_phase2/test_concurrent_metadata_merge.py
python run_ui.py
```

7. In Audit select `Rejected Images` or search PN, e.g. `IRF634`, `SSP5N90A`. Select `Accept Rejected Image` **only if the physical part geometry is correct and the candidate file exists**. The resulting branded WebP is in `Final/<PN>.webp`. `OSG65R130PT3Z` is a **regeneration failure**, not an existing rejected image: it must be queued for a fresh image regeneration via the ordinary Phase1 workflow.

8. Verify 6 manual-PDF items and 24 Sales-only candidates from the incident. Approve **only after** checking all required facts, category, image, SEO and datasheet eligibility. Previously approved products whose bundle is inconsistent require separate human review. Run a small Phase3 pilot before any large batch.

## Tests and limitations

- Local offline test run: 96 tests passed (`tests_v3`, `tests_phase2`, `tests_phase3`, `tests_altimate_v100`, `tests_altimate_v101`).
- Extended tests importing the complete GUI/Phase1 could not be collected locally because the container lacks the `openai` Python package and pip has no Internet. This is an **environmental limit**, not a claim of full integration pass.
- `audit(1).zip` contains metadata, runtime states and product snapshots but not physical PDFs. A dry-run against a clone of the 676 metadata JSONs, with six **synthetic test PDFs**, proposed 6 manual PDF repairs and 26 Sales-only repairs (24 unapproved + 2 previously approved); this is **not verification of the real PDFs**. The final result on Windows may differ depending on real PDF assets and history.
- No API calls/live Windows UI pilot or WordPress publishing were run here. Recommended release status: **controlled pilot / human verification required**, not production-certified.
