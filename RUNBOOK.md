# RUNBOOK — Tavakol Integrated V1.2

## 1. Migration from V1.1

Copy these runtime folders from the previous repo:

```text
input/
metadata/
output/
Final/
datasheets/
phase3_outputs/
work/
runtime_state/
products/
```

Copy secrets/config separately:

```text
.env
proxies.txt
```

Do **not** copy the old `audit needed/` folder. V1.2 replaces it with the Admin Audit UI.

## 2. Normal input

Put unknown-PN photos in:

```text
input/
```

## 3. Trusted PN input

If the PN is already known, save the original image as:

```text
PN_input/PART_NUMBER.jpg
```

The filename becomes the PN authority and OCR PartNumber extraction is skipped.

## 4. Run in Windows CMD

```cmd
cd C:\PATH\TO\Tavakol_Phase1_Phase2_Phase3_Integrated_V1.2
python -m pip install -r requirements.txt
python run_ui.py
```

CLI:

```cmd
python run_integrated.py
```

## 5. Admin Audit

The Audit button is disabled while the pipeline is running and enabled when it is stopped.

Audit statuses:
- red `AUDIT NEEDED`
- green `FINALIZED`

Approve creates:

```text
ready_for_upload/PART_NUMBER/
```

Disapprove reasons:
- wrong part number
- image regeneration needed
- wrong data sheet
- SEO content regeneration needed

Selected repairs are checkpointed and executed on the next `Start`.

Wrong PN behavior:
- type the corrected PN in the inline entry beside `wrong part number`.
- Wrong Datasheet and SEO Regeneration checkboxes are disabled because Phase 2/3 are automatically invalidated by PN correction.
- If old PN and corrected PN both end in `NOT_FOUND_CONFIRMED`, previous no-datasheet SEO is repaired by deterministic PN replacement and no Phase-3 API call is made.

## 6. Validation

```cmd
python -m pytest -q tests_phase2 tests_phase3
python validate_schemas.py
```


## Manual datasheet
`manual_required` blocks Phase 3. Stop the pipeline, open Audit, drop the exact PDF (or Browse PDF), then Start again.
