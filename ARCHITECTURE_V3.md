# Tavakol Electronics — Integrated V3.0 Architecture

```text
input/ or PN_input/
  -> Phase 1: precheck -> regeneration -> structural validation -> OCR/PN authority -> final WebP
  -> Phase 2: exact datasheet identity + manufacturer + physical package
  -> Phase 3: facts/content/validator + package fallback only when unresolved
  -> Admin Audit: APPROVED + FINALIZED
  -> Canonical Bundle: ready_for_upload/<PN>/
  -> Phase 4: WooCommerce Draft
  -> human WordPress review -> manual Publish
```

## Truth boundaries

- `metadata/<PN>.json`: live canonical Source of Truth.
- `runtime_state/`: resumable execution checkpoints, not product truth.
- `runtime_state/publisher/<PN>.json`: detailed Phase 4 checkpoint and duplicate guard.
- `ready_for_upload/<PN>/`: immutable-ish snapshot of the Admin-approved release candidate. Publisher reads only this contract.
- `work/`: intermediate artifacts.

## Frozen V3 rules

1. Exact PN only; no fuzzy datasheet substitution.
2. Product title = `آی سی <PN>` programmatically.
3. Package resolution order: Phase 2 external exact evidence first; Phase 3 datasheet PDF only as fallback.
4. Publisher never guesses PN/package/content.
5. Admin Audit precedes Phase 4.
6. Publisher is resilient per product/step but Report marks Phase 4 successful only if every required step succeeds.
7. Phase 4 creates Draft only; never automatic Publish.
