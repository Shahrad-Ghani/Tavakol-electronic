# Catalog Automation Agent — Integrated V4.0.4 Patch Report

## Purpose
V4.0.4 guarantees that final Phase-3 customer content has an introduction H2 containing the exact Part Number. The repair is deterministic and category-aware, so it does not spend an additional model/API call and cannot invent technical facts.

## Pipeline position
`Facts → Main Content → Validator / Fact Safety Repair → Density/Local Repairs → Tone Editor → Intro Header Repair → SEO Snippet Finalization → Final Semantic Audit → HTML Renderer → Phase3 Output`

## Rule
- Accept an existing H2 if it contains both `معرفی` and the exact PN.
- Otherwise insert `## **معرفی {category_label} {PN}**` at the top of `body_markdown`.
- The category label comes from the canonical product identity / Category Registry.
- The repair is idempotent: a second run detects the H2 and makes no duplicate.
- No technical specification, number, package, manufacturer or application fact is invented by this stage.

## Validation / observability
- Final JSON stores `validation.intro_heading.status`, `expected`, `found`, `occurrences`, `matched_headings`, and `programmatic_repair_applied`.
- Integrated Phase-3 logs report whether the header was `INSERTED` or already `PRESENT`.
- The repaired candidate is passed back through local structure/fact-safety/style evaluation before SEO snippet finalization and final semantic audit.
- HTML is still rendered deterministically from `body_markdown`; the LLM does not generate the HTML.

## Regression coverage
V4.0.4 adds tests for:
1. missing intro H2 → category-aware insertion;
2. existing natural intro H2 → no rewrite;
3. idempotent rerun → no duplicate H2;
4. Markdown repair → expected HTML `<h2>` output;
5. end-to-end mock Phase-3 export → `validation.intro_heading` recorded and final HTML contains the heading.

## Validation
- `python -m pytest -q` → **108 passed**
- `python -m compileall -q .` → **PASS**
- `python validate_schemas.py` → **12/12 schemas PASS**

