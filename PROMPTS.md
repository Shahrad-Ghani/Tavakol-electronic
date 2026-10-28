# Prompt Pack — V3.0

## OCR
- Prompt version: `v4.0-dual-image-cropped-fallback-ocr`
- Input policy:
  - Image A = original phone photo derivative view (character authority)
  - Image B = regenerated/cleaned derivative view (readability aid only)
  - both images are deterministically preprocessed into OCR views containing a tight component crop plus an enlarged marking crop
- Model policy:
  - primary = `gpt-5.6-luna`
  - fallback = `gpt-5.6-sol`
- Core rules:
  - prefer original on readable character conflicts
  - use regenerated image only to clarify weak text
  - block low-confidence identities
  - block disagreement between primary and fallback OCR models
  - explicitly re-check common confusions: `B↔8`, `O↔0`, `I/l↔1`, `S↔5`, `Z↔2`, `G↔6`, `C↔G`, `D↔0/O`, `U↔V`, `T↔7`, `-`, `/`, `+`

## Regeneration
- Unchanged from integrated V2.0

## Identity validation
- Unchanged from integrated V2.0
