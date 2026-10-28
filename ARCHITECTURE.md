# Tavakol Phase 3 ALitmate V1.1 — Frozen Architecture

## 1. Objective

Phase 3 converts an exact Phase-2 datasheet and product identity into Persian WooCommerce-ready SEO content while minimizing PDF-model cost and keeping technical claims bounded by a structured FINAL_FACTS contract.

Core policy:

> PDF is processed once in the normal path and at most twice in the fallback path. After `final_facts.json` is written, PDF access is closed for Writer, Tone Editor and Final Auditor.

False Null remains preferable to False Positive.

---

## 2. Runtime flow

```text
Exact Phase-2 Datasheet PDF
        │
        ▼
First up to 5 pages
        │
        ▼
GPT-5.6 Luna
PRIMARY FACT EXTRACTION — 1 PDF call
        │
        ▼
Local Fact Coverage Gate
        │
   ┌────┴──────────────┐
   │ sufficient        │ insufficient / identity not confirmed
   │                   ▼
   │             GPT-5.6 Luna / no second PDF call
   │             ONE PDF FALLBACK
   │                   │
   └──────────┬────────┘
              ▼
        FINAL_FACTS JSON
              │
              ╳ PDF CLOSED
              │
              ▼
       GPT-5.6 Luna Writer
              │
       Local SEO / Safety / Structure
              │
       Luna targeted Attempt 2 if needed
              │
       best normalized SEO < 60 after 2 Luna attempts?
          │                 │
         no                yes
          │                 ▼
          │           GPT-5.6 Luna / no second PDF call Writer once
          └────────────┬────┘
                       ▼
              Local Normalizer
                       ▼
               GPT-5.4 mini
              Tone/Naturalness Editor
                       ▼
               Local Validators
                       ▼
               GPT-5.4 mini
              FINAL_FACTS-only Audit
                       ▼
                PASS / REVIEW
```

---

## 3. PDF cost policy

### Normal path
- PDF calls: **1**
- Model: `gpt-5.6-luna`

### Fallback path
- PDF calls: **2 maximum total**
- Call 1: `gpt-5.6-luna`
- No Call 2 in V2.1; sparse coverage is retained and reported
- No third PDF attempt.

### PDF window
Only the first up to 5 pages are sent to models. The original PDF remains untouched.

`pdf_window.json` records:
- original page count
- pages sent to models
- whether the model window was truncated
- source/model-window hashes

Intentional truncation is **not** interpreted as proof that the original datasheet is partial.

---

## 4. Fact extraction

Primary extraction is broad, not a six-field lookup.

The extractor may return up to 16 directly supported SEO-useful facts, including but not limited to:
- voltage / voltage rating / supply voltage
- current / current rating / supply current
- package
- application / function
- frequency / bandwidth
- operating temperature
- switching time
- gain
- logic levels
- resistance
- power
- isolation
- topology
- output characteristics
- thresholds

The six priority groups are fallback-routing hints only. They are **not a whitelist**.

### Priority fact groups
1. voltage
2. current
3. package
4. application_or_function
5. frequency
6. operating_temperature

### Coverage gate
Primary Luna extraction is considered sufficient when either:

```text
useful facts >= 5 AND priority categories >= 3
```

or:

```text
useful facts >= 8
```

Exact target identity must also be confirmed in the visible PDF window.

If the coverage gate fails in V2.1, no second model call is made. Safe Luna facts are retained and the coverage remains sparse/insufficient for downstream review.

V2.1 performs exactly one PDF extraction call. Any safe facts that remain are used conservatively; missing evidence is never filled by a second expensive call.

---

## 5. FINAL_FACTS contract

`work/fact_extraction/PART_NUMBER/final_facts.json` is the only technical source after the PDF stage.

Writer-authorized fields include:
- parameter
- claim
- value_text
- unit
- condition
- section
- scope
- seo_usage

Rejected/audit material does not enter the Writer knowledge boundary.

Absolute Maximum facts stay `LIMIT_ONLY`.

Family-sensitive facts such as package/pins require `TARGET_ONLY` scope.

---

## 6. Content model router

### Cheap Writer
`gpt-5.6-luna`

- Attempt 1: full generation
- Attempt 2: targeted body repair only when needed
- local deterministic normalization occurs before expensive Writer escalation

### Expensive Writer
disabled in V2.1

Allowed only when:
- two Luna attempts have run,
- a safety-valid candidate exists,
- local normalization has already been tried,
- best normalized SEO score is **below 60**.

V2.1 has no expensive writer escalation. SEO score itself is not a publication gate; safety, core structure, tone and factuality decide publishability.

---

## 7. Local Normalizer

Deterministic and API-free repairs include:
- duplicate FAQ merge
- duplicate sentence removal
- repeated warning cleanup
- empty section repair/removal
- excessive length repair
- fine length trim near hard ceiling
- banned meta-language cleanup
- exact internal-link policy insertion/repair
- density repair as the final local normalization step

Density repair may replace safe prose occurrences of the exact PN with `این IC`. It never changes Heading occurrences, tables or links.

---

## 8. Writer tone contract

Writer must sound natural from Attempt 1.

Forbidden customer-facing patterns include:
- `در این صفحه ...`
- `بر اساس داده‌های مجاز/تأییدشده ...`
- pipeline / validator / prompt / dataset language
- unnecessary English/German terms
- raw LaTeX
- repetitive warnings
- SEO filler

If fact coverage is sparse, Writer must shorten the technical portion rather than invent facts.

---

## 9. Tone Editor

Model: `gpt-5.4-mini`

Role: Editor, not author.

Allowed:
- KEEP
- REWRITE
- SHORTEN
- MERGE
- DELETE
- TRANSLATE
- REORDER

Forbidden:
- adding a technical fact
- adding a new application
- changing value/unit/condition/package
- changing URLs

`ai_like_style_score` is diagnostic only and is never a standalone hard gate.

---

## 10. Final semantic audit

Model: `gpt-5.4-mini`

The auditor receives:
- exact PN
- verified identity
- FINAL_FACTS
- final content

It receives **no PDF**.

Checks:
- wrong values/signs
- wrong units
- materially changed conditions
- min/typ/max corruption
- variant leakage
- unsupported technical claims
- package/application/compatibility/replacement inference
- Absolute Maximum presented as operating data

Missing a fact in content is not a failure.

---

## 11. Quality evaluation policy

PASS rate is operational only and is not the primary quality metric.

Primary scorecard dimensions:
- useful fact count
- priority fact coverage
- PDF calls per technical product
- PDF calls per technical product (target: exactly 1)
- local factual safety
- facts-only audit status
- content usefulness / structure
- tone naturalness diagnostics
- SEO score / density / word count
- total estimated cost
- Expensive writer escalation rate (fixed at 0 in V2.1)

For true Fact Precision/Recall, use manually adjudicated Golden fact files with `run_evaluation.py`.

---

## 12. Work artifacts

```text
work/fact_extraction/PART_NUMBER/
├── datasheet_first5.pdf
├── pdf_window.json
├── primary_extraction.json
├── fallback_extraction.json       # only if coverage gate fails
├── source_validation.json
├── coverage.json
└── final_facts.json

work/content/PART_NUMBER/
├── attempts/
├── tone_editor.attempt_1.raw.json
├── facts_only_final_audit.json
├── content.md
├── content.html
└── product.json
```

---

## 13. Frozen model roles

```text
PDF Primary Extractor : gpt-5.6-luna
PDF Fallback          : DISABLED
Cheap Writer          : gpt-5.6-luna
Expensive Writer      : DISABLED
Tone Editor           : gpt-5.4-mini
Facts-only Auditor    : gpt-5.4-mini
```

There is no expensive PDF or writer tier in the V2.1 active path.
---

## 13. V1.1 freeze patches

### SEO publication policy
`seo_threshold=80` remains a reporting/quality benchmark and may still guide cheap retry behavior, but SEO score alone cannot force `REVIEW_REQUIRED`.

Hard publication gates remain:
- exact identity / hard gates
- Fact Safety
- non-editorial structure requirements
- Tone/Naturalness safety
- FINAL_FACTS-only semantic audit

Keyword-density and word-count envelope failures are editorial quality metrics, not hard publication gates.

### Tone eligibility
Tone Editor may run when the only content-contract failures are keyword-density or word-count envelope failures. It still cannot run through missing required sections, broken internal links, empty FAQ answers, Hard Gate failure or Fact Safety failure.

### RTL negative normalization
Before local Fact Safety comparison, Persian/RTL postfix-negative numeric forms such as `۰٫۸۸- mA` are canonicalized to leading-minus form (`-0.88 mA`). Compact positive ranges such as `3-12 V` are preserved as ranges.

### PDF window remains frozen
Only the first **up to 5 pages** of each datasheet are sent to the PDF extractor. The original PDF remains untouched. Luna is called exactly once; there is no PDF fallback call.

---

## V1.2 implementation sequencing note (architecture unchanged)

`phase3_Altimate_V1.2` does not change the frozen V1.1 architecture, prompts, models, thresholds, or knowledge boundaries. It only removes post-Tone exact-PN density mutation. Density repair remains the final pre-Tone local normalization step; after Tone Editor, local validators measure/report density without rewriting the edited customer-facing prose.


---

## Integrated V1.2 additions

- Admin Audit is a stopped-pipeline-only human gate.
- Products are visually reviewed original-vs-final with identity, datasheet and SEO diagnostics.
- Approval creates a deterministic `ready_for_upload` bundle; no WordPress write occurs in V1.2.
- Disapproval invalidates only the selected scope and reuses the normal orchestrator on the next Start.
- Wrong-PN correction is identity-authoritative and invalidates Phase 2/3, except for the explicit old/new `NOT_FOUND_CONFIRMED` local PN-replacement path.
- Legacy `audit needed/` folder workflow is removed.
- `PN_input/` provides trusted filename PartNumber input and skips OCR PartNumber extraction only; image quality/identity gates remain active.

## V4.0.4 deterministic intro-heading integrity stage

After Tone Editor selects the final body, Phase 3 now runs a local `Intro Header Repair` before SEO snippet finalization, final semantic audit and HTML rendering. An H2 is considered valid when it contains both `معرفی` and the exact Part Number. If absent, the pipeline inserts `## **معرفی {category_label} {PN}**` using the immutable run category. The repair adds no technical facts, performs no API call, is idempotent, and is re-evaluated through the normal local validators before publication state is finalized.

