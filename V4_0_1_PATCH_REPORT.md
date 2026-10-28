# Catalog Automation Agent — Integrated V4.0.1 Patch

## Fixed
- Integrated product schema now explicitly accepts canonical `identity.category_context`; validation remains strict (`additionalProperties: false`).
- Fact Safety package matching now accepts a less-specific verified-compatible TO package claim (`TO-92` when `TO-92 3L` is verified) but still rejects contradictory or more-specific unsupported claims.
- Added explicit targeted Fact Safety repair pass. When writer output remains unsafe, the previous generated body and exact Fact Safety failures are sent back to the writer for one bounded correction attempt.
- Added `prompts/fact_safety_retry.md` and prompt-manifest tracking.
- Added `fact_safety_repair_max_attempts` configuration (default: 1).

## Output contract clarification
The main content model returns strict JSON. Customer content is carried in `body_markdown` (Markdown text), not HTML. HTML is rendered deterministically later by `phase3_final/html_renderer.py`.

## Validation
- `pytest`: 97 passed.
- `compileall`: passed.
- No live OpenAI or WordPress production calls were used for validation.
