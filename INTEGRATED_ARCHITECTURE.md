# Integrated Architecture — Phase 1 + Phase 2 + Phase 3 V1.0

## 1. Design rule

سه فاز business logic مستقل خود را حفظ می‌کنند. Merge در سطح orchestration، state handoff و final schema انجام شده است؛ Phase 3 Altimate V1.2 از نظر PDF/FINAL_FACTS/model routing/prompt contract redesign نشده است.

## 2. Streaming topology

```text
                     ┌─────────────────────────────┐
Input images ──────► │ PHASE 1 WORKER (sequential)│
                     └──────────────┬──────────────┘
                                    │ stable exact OCR PN event
                                    ▼
                            Queue P2 immediately
                                    │
                     ┌──────────────▼──────────────┐
                     │ PHASE 2 WORKER              │
                     │ exact identity/datasheet    │
                     │ + Mouser Package/Case       │
                     └──────────────┬──────────────┘
                                    │ terminal datasheet decision
                                    ▼
                            Queue P3 immediately
                                    │
                     ┌──────────────▼──────────────┐
                     │ PHASE 3 WORKER              │
                     │ Altimate V1.2 frozen core   │
                     └──────────────┬──────────────┘
                                    │
                                    ▼
                         products/PART_NUMBER.json
```

Phase 1 بعد از emit کردن PN متوقف نمی‌شود؛ Logo/Final image را کامل می‌کند و سپس سراغ تصویر بعدی می‌رود. بنابراین سه فاز روی محصولات مختلف overlap دارند.

## 3. Worker policy

- P1: یک worker sequential برای حفظ رفتار frozen image pipeline و cost routing.
- P2: یک worker؛ هر item فوراً `process_batch([item])` می‌شود. Mouser maximum batch=10 دیگر latency orchestrator ایجاد نمی‌کند.
- P3: یک worker برای cost/control قابل پیش‌بینی.
- Queueها deduplicated هستند.

## 4. Phase-2 terminal states accepted by P3

```text
completed
not_found_confirmed
manual_required
identity_found_unresolved
```

`completed` با Exact local PDF وارد Technical path می‌شود. حالت‌های بدون PDF به Commercial-only Phase 3 می‌روند. Failureهای source/network که هنوز terminal نیستند به P3 ارسال نمی‌شوند.

## 5. Package contract

Phase 2:

```text
Exact Mouser MPN
  -> ProductAttributes
  -> Package / Case
  -> phase2.datasheet.package evidence
```

`Packaging` فروشگاهی هرگز به package فیزیکی تبدیل نمی‌شود.

Phase 3:

```text
Exact datasheet -> FINAL_FACTS -> TARGET_ONLY PACKAGE
```

Mouser package داخل Writer knowledge boundary تزریق نمی‌شود؛ بنابراین FINAL_FACTS contract شکسته نشده است.

Final reconciliation:

```text
Mouser == Datasheet -> CONFIRMED
Mouser != Datasheet -> CONFLICT_REVIEW, Datasheet value wins
Datasheet only       -> DATASHEET_VERIFIED
Mouser only exact    -> MOUSER_EXACT_ONLY
none                 -> UNKNOWN
```

## 6. Concurrency-safe metadata

بعد از PN-ready، P1 و P2 می‌توانند یک Metadata را هم‌زمان به‌روزرسانی کنند. برای جلوگیری از lost update:

- Phase 1 canonical save هنگام write، Phase-2-owned fields جدید موجود روی disk را حفظ می‌کند.
- Phase 2 از `save_phase2()` استفاده می‌کند و فقط fieldهای مالک خودش را روی آخرین Phase-1 state patch می‌کند.
- write نهایی atomic است.

Phase-2-owned fields:

```text
datasheet
manufacturer
country
phase2_history
status.datasheet
```

## 7. Checkpoint / recovery

Checkpointها مستقل از پایان batch هستند:

```text
metadata/*.json          P1/P2 durable checkpoint
work/fact_extraction/*   P3 fact checkpoint
work/content/*           P3 attempt/tone/audit checkpoint
phase3_outputs/*.json    P3 final state
runtime_state/*.json     orchestrator checkpoint
products/*.json          final integrated snapshot
```

Network failure = wait and retry from existing checkpoints.
API auth/credit failure = fatal stop, checkpoints preserved.

## 8. Phase 3 no-MD runtime policy

Generated Markdown files حذف شده‌اند. `body_markdown` همچنان structured content field داخل JSON است تا RankMath-like validator و HTML renderer بدون تغییر semantic کار کنند.

Runtime Phase3 artifacts:

```text
phase3_outputs/PART_NUMBER.json
phase3_outputs/PART_NUMBER.html
```

## 9. Final schema gate

قبل از `products/PART_NUMBER.json`:

```text
Phase1+2 metadata -> metadata_schema.json
Phase3 JSON       -> phase3_final_product.schema.json
Merged JSON       -> integrated_product.schema.json
```

هر Failure مانع نوشتن JSON نهایی Merge می‌شود.

## 10. Publishing boundary

Publishing فعلاً side effect ندارد. `publishing_preview` یک adapter-ready payload است. WordPress/RankMath REST/plugin integration باید در مرحله بعد ساخته شود و از همین payload استفاده کند؛ direct DB write توصیه نمی‌شود.

---

# Integrated V1.2 — Admin Audit + PN_input

## Admin Audit lifecycle

Admin Audit is deliberately outside the active worker lifecycle. The UI enables `Audit` only when the orchestrator is not running.

```text
Pipeline stopped
↓
Admin Audit opens
↓
item classified as AUDIT_NEEDED or FINALIZED
↓
Approve ───────────────→ ready_for_upload/<PN>/
      or
Disapprove
↓
selected scope is invalidated atomically
↓
DISAPPROVED_PENDING_REPROCESS
↓
next Start
↓
normal orchestrator checkpoint/recovery path
↓
READY_FOR_REAUDIT
```

This prevents a human decision from racing Phase-1/2/3 background writes.

### Audit scope routing

| Admin issue | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| image regeneration needed | rerun image regeneration/validation/logo/final | keep | keep |
| wrong data sheet | keep | rerun | rerun + force fact extraction |
| SEO content regeneration needed | keep | keep | rerun |
| wrong part number | keep unless image regen also selected | rerun for corrected PN | normally rerun |

`wrong part number` suppresses separate `wrong data sheet` and `SEO content regeneration needed` options because the corrected identity already invalidates both downstream phases.

### No-datasheet identity-correction exception

If and only if:

```text
old wrong PN -> NOT_FOUND_CONFIRMED
corrected PN -> NOT_FOUND_CONFIRMED
```

and a previous sales-only Phase-3 artifact exists, V1.2 reuses that artifact and replaces the PN programmatically in JSON/HTML. No Phase-3 model call is made. Any other corrected-PN result follows the normal Phase-3 generation path.

### Invalidation history

Artifacts explicitly rejected by Admin are not silently overwritten. Invalid datasheets, old Phase-3 outputs, content/fact work directories and old Final images (when image regeneration is requested) are moved under:

```text
audit_history/<UTC_TIMESTAMP>_<SOURCE_REF>_<REASON>/
```

Active pipeline directories then contain only the current identity/state.

## PN_input

`PN_input/` is an alternate Phase-1 source for products whose Part Number is already known by the user.

```text
PN_input/PART_NUMBER.jpg
↓
PartNumber authority = USER_FILENAME
↓
Precheck
↓
Regeneration
↓
Identity validation
↓
OCR PartNumber = SKIPPED
↓
Logo / Final
↓
Phase 2 / Phase 3
```

The metadata records the source under `original_imag` and the OCR section is explicitly stored as a manual override with authority `PN_INPUT_FILENAME` rather than pretending an OCR model produced the PN.
