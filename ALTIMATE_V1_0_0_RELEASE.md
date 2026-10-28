# Catalog Automation Agent — Altimate V1.0.0

## Status
Code-level release candidate; not live-verified with the user's API keys, WordPress, or Windows UI.

## Changes
- Phase1 thread pool (default 10) and Phase3 isolated-worker pool (default 10). Phase2 remains one streaming worker.
- Manual filename PN enqueues Phase2 before Phase1 regeneration/validation. Phase3 starts after Phase2's eligible terminal decision.
- Existing pending Phase3 jobs resume even when input_PN is empty.
- Completed Phase3 metadata with intentionally omitted HTML/JSON does NOT automatically trigger expensive regeneration. Restore phase3_outputs or explicitly request SEO regeneration.
- Shared 429 cooldown for native OpenAI clients. This has no made-up RPM/TPM cap. Mouser stays one worker with existing rate control.
- Merge-safe metadata Phase1 write preserves latest Phase2, Phase3, audit and publisher state; single-process RLock and atomic temp replacement.
- Tone runs on generated text regardless of local fact/structure gate; noncompliant tone output falls back to pre-tone text and is recorded. Snippet/semantic validation no longer skipped merely because Tone output was rejected. Publication still requires fact safety, identity and semantic safety.
- Audit shows concrete codes and actionable reasons, plus **Accept Rejected Image**. This copies no fabricated facts; it runs canvas, logo, WebP and records human authorization, preserving the original rejection.
- WordPress Duplicate Guard, save_attributes prohibition and Save Draft policy unchanged.

## Prepare the working directory
1. Extract into a NEW directory. Keep your old V4.0.6.1 untouched and backed up.
2. For an existing live V4.0.6.1 installation, run `python upgrade_from_v4061.py --source "C:\\path\\to\\Catalog_Automation_Agent_Integrated_V4_0_6_1" --dry-run` then, after reviewing it, re-run with `--apply`. The tool copies current state/files including your private `.env` and `proxies.txt` LOCAL ONLY, makes backups of conflicts and does not modify the old installation. (Alternatively copy files manually.)
3. Copy existing `datasheets/`, `phase3_outputs/`, `products/`, `work/`, `Final/`, `runtime_state/`, `input/` and `input_PN/` from your installation if you want continuity. Empty placeholder folders are provided, but historical assets were deliberately omitted from the submitted repository. Do not overwrite the new code files.
4. The 3 rejected image candidates are provided in `output/`; their original photos are already in `input_PN/` and also backed up under `sample_original_images/`, so Audit can display both sides. **Open Audit and accept images BEFORE pressing Start** to avoid unnecessary regeneration.
5. Open `python run_ui.py`. With the pipeline IDLE, click Audit > find `SSP5N90A`, `SSP6N60`, `SSS2N60` > **Accept Rejected Image**, inspect output `Final/<PN>.webp`. This action does not approve/publish the product.
6. To resume pending SEO jobs, choose your existing product category and Start even with an empty input_PN folder; eligible Phase3 jobs will be processed by 10 workers. Datasheet `web_error` items still require human decision in Audit.
7. Before site writes, check any generated draft through WordPress. Publisher remains Draft-only.

## Tests
`python -m pytest -q tests_altimate_v100 tests_phase2/test_concurrent_metadata_merge.py`

## Known limits
- New 10/1/10 orchestration must be tested on Windows with valid OpenAI/Mouser credentials. Shared cooldown applies to terminal 429 errors; the SDK also performs built-in retries.
- **Not all historical Metadata are production-clean**; no bulk mutation/migration of historical products is performed. Products deliberately resumed from unfinished states will have their own phase checkpoints updated.
- Full Rate Limit headers, pricing and plan-specific account quotas cannot be determined from model names alone.
- Output bundles should always be manually audited before publication.
