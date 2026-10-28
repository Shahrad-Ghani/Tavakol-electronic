# Catalog Automation Agent — Integrated V4.0.6

> **V4.0.6:** اصلاح چرخه Publisher بدون دستکاری Duplicate Guard: حذف کلیک AJAX دکمه `save_attributes`، انتظار برای آزادشدن overlay های WooCommerce، انتخاب Category بدون کلیک اضافه روی تب از پیش فعال، و **تلاش برای Save Draft پس از اجرای مراحل، حتی اگر مرحله‌ای شکست بخورد**. در این حالت وضعیت `DRAFT_SAVED_WITH_WARNINGS` ثبت می‌شود و هرگز موفقیت کامل تلقی نمی‌گردد. همچنین آپلود دستی PDF در Audit برای `datasheet.status=failed` دوباره در دسترس است و پس از اتصال، استخراج Facts و محتوای SEO برای اجرای بعدی invalidate می‌شوند. [V4_0_6_PATCH_REPORT.md](V4_0_6_PATCH_REPORT.md)

> این بسته شامل اطلاعات اجرایی آپلودشده (`input_PN`, `Final`, `datasheets`, `metadata`, `ready_for_upload`, `runtime_state`) است. فایل‌های دارای رمز/کلید `.env` و `proxies.txt` در ZIP نیستند؛ در ویندوز از نسخه خصوصی خود کپی کنید. **شناسه‌های وردپرس و Duplicate Guard حفظ شده‌اند**، پس محصولی که قبلاً در سایت شناخته شده دوباره ساخته نمی‌شود. ذخیره ویژگی‌ها پس از حذف دکمه AJAX هنوز باید با آزمایش دستی در ووکامرس واقعی تأیید شود.

> **V4.0.5:** اصلاح Publisher برای Category و Edit Snippet و SKU، ویژگی‌های MOSFET، مدیریت محلی Edit Category و تست‌های رگرسیون. جزئیات: [V4_0_5_PATCH_REPORT.md](V4_0_5_PATCH_REPORT.md). فایل‌های محرمانه `.env` و `proxies.txt` عمداً از ZIP حذف شده‌اند؛ آن‌ها را روی رایانه خود با استفاده از `.env.example` و `proxies.example.txt` بسازید.

`Integrated V4` نسخه چنددسته‌ای End-to-End پایپ‌لاین توکل الکترونیک است و روی `Integrated V3.1` توسعه یافته است. مسیر کلی همچنان Phase 1 → Phase 2 → Phase 3 → Admin Audit → Phase 4 Publisher است، اما Category اکنون یک ورودی canonical برای کل Batch است.

> **V4.0.4:** تمام اصلاحات V4.0.3 حفظ شده‌اند. در Phase 3 یک مرحله deterministic جدید بعد از Tone Editor اضافه شده که وجود H2 معرفی شامل PN را تضمین می‌کند. اگر هدر معرفی وجود نداشته باشد، بدون API call هدر category-aware مانند `## **معرفی ماسفت 2N4093**` اضافه می‌شود؛ سپس خروجی دوباره local-validate شده و بعد وارد SEO Snippet / Final Semantic Audit / HTML rendering می‌شود.

## تغییرات اصلی V4

- UI با نام **Catalog Automation Agent** و پنل‌های `Image Processing`، `Datasheet Resolution` و `Content Generation`.
- دو Mode ورودی:
  - **Default**: فقط `input/` و OCR عادی Part Number.
  - **Manual**: فقط `input_PN/`؛ نام فایل Authority قطعی PN است و OCR PN اجرا نمی‌شود.
- انتخاب **Category قبل از هر Start اجباری** است و برای Start بعدی باید دوباره انتخاب شود.
- `config/category_registry.json` منبع واحد Categoryهاست: نام، Parent/Child، Term ID واقعی WooCommerce، URL، title prefix، density phrase، slug rule و technical-focus.
- Product title، Density Repair، Internal Link، Slug و Publisher همگی Category-aware هستند.
- Phase 3 دارای SEO Snippet Agent مستقل برای `SEO Title` و `Meta Description` است؛ Writer اصلی و Tone Editor مستقل باقی می‌مانند.
- Meta Description در WooCommerce Short Description و Rank Math Meta Description ثبت می‌شود؛ SEO Title و category-aware permalink نیز در Rank Math Snippet نوشته می‌شوند.
- Tone Editor دیگر به علت `publishable=false` زودهنگام Skip نمی‌شود؛ فقط Hard Safety/Identity gate واقعی می‌تواند مسیر را متوقف کند.
- Package normalization از ذخیره جمله کامل جلوگیری می‌کند؛ Package unresolved همچنان مانع Draft شدن محصول نیست.
- بعد از تکمیل Phase 2، `assets/banner.png` روی بالای صفحه اول Datasheetهای Batch قرار می‌گیرد و به `https://tavakolelectronic.com/` لینک می‌شود. این تبدیل idempotent است.
- Canonical Bundle قرارداد V4 دارد و Publisher فقط Consumer داده‌های canonical است.
- Phase 4 همچنان **Save Draft Only** است و Auto Publish ندارد.

## نصب و اجرای سریع در Windows

```cmd
cd C:\PATH\TO\Catalog_Automation_Agent_Integrated_V4
python -m pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
copy proxies.example.txt proxies.txt
python run_ui.py
```

در `.env` حداقل `OPENAI_API_KEY` و در صورت استفاده از Phase 2، `MOUSER_API_KEY` را تنظیم کنید. برای Publisher نیز `WP_USERNAME` و `WP_PASSWORD` لازم است. Secretها را داخل کد یا Git قرار ندهید.

### اجرای Pipeline از UI

1. برای حالت عادی تصاویر را در `input/` قرار دهید.
2. برای PN قطعی، تصویر را با نام دقیق Part Number در `input_PN/` قرار دهید؛ مثال: `input_PN/IRF3205.jpg`.
3. برنامه را با `python run_ui.py` باز کنید.
4. `Mode` را انتخاب کنید. مقدار Mode بین اجراهای برنامه ذخیره می‌شود.
5. `Category` را حتماً انتخاب کنید. Category برای تمام فایل‌های جدید همان Run اعمال می‌شود.
6. `Start` را بزنید. بعد از شروع موفق، Category در UI خالی می‌شود تا برای Start بعدی دوباره آگاهانه انتخاب شود.
7. پس از پایان Pipeline، از Audit برای بررسی و Approve/Disapprove استفاده کنید.
8. فقط محصولات Approved/Finalized می‌توانند Canonical Bundle بسازند و وارد Publisher شوند.

اگر Manual انتخاب شود و `input_PN/` خالی باشد، UI خطای `Folder is empty!` می‌دهد. اگر Category انتخاب نشده باشد، Start با `category not seleccted!` متوقف می‌شود.

## Publisher / WordPress

به‌صورت پیش‌فرض:

```env
ALLOW_SITE_WRITE=false
```

برای تست Dry Run همین مقدار را نگه دارید. فقط وقتی برای تست واقعی WordPress آماده هستید آن را به `true` تغییر دهید. Publisher همچنان فقط **Save Draft** می‌زند.

```cmd
python run_publisher.py
```

Publisher از Category/Term IDs، عنوان، HTML، SEO Title، Meta Description، Slug، تصویر و Datasheet موجود در Canonical Bundle استفاده می‌کند و این مقادیر را دوباره حدس نمی‌زند.

## CLI

```cmd
python run_integrated.py --mode default --category ic
python run_integrated.py --mode manual --category mosfet
python run_publisher.py
python run_report.py
```

در V4، CLI نیز `--mode` و `--category` را اجباری می‌کند. Engine فقط برای سازگاری فراخوانی‌های داخلی/Legacy fallback `ic` دارد؛ مسیرهای رسمی UI و CLI هر دو Category را صریح دریافت می‌کنند.

## تست آفلاین / Mock

```cmd
set PYTHONPATH=.
python -m pytest -q
python validate_schemas.py
```

Release تحویلی V4 با تست‌های آفلاین/Mock و Regression بررسی شده است؛ تست زنده OpenAI API و WordPress عمداً انجام نشده و باید در محیط Production خودتان انجام شود.

## پوشه‌های مهم

```text
input/                         Default-mode images
input_PN/                      Manual-mode images; filename = authoritative PN
metadata/<PN>.json             live pipeline Source of Truth
datasheets/<PN>.pdf            datasheets; V4 banner is injected after Phase 2 batch
work/...                       intermediates
runtime_state/...              resume/checkpoints
ready_for_upload/<PN>/         approved canonical publication bundle
assets/banner.png              datasheet promotional banner
config/category_registry.json  canonical category registry
```

## Category Registry

V4 دارای 26 Child Category ثبت‌شده با URL و Term ID واقعی WooCommerce است. برای افزودن Category جدید، به‌جای ایجاد if/else در Writer/Publisher، رکورد Registry را اضافه و Schema/Testها را به‌روزرسانی کنید.

---

# Historical V3.1 documentation

# Tavakol Electronics — Integrated V3.1

نسخه V3.1 ریپوی واحد End-to-End پروژه است: Phase 1 + Phase 2 + Phase 3 + Admin Audit + Phase 4 Publisher + Excel Report.

## تغییرات قفل‌شده V3.0 + Patch V3.1

- Metadata V3 (`schema_version: 3.0`) منبع حقیقت جاری Pipeline است. محصولات جدید مستقیماً V3 می‌سازند؛ داده‌های Legacy با Migrator تبدیل می‌شوند.
- عنوان محصول دیگر توسط LLM ساخته نمی‌شود و همیشه programmatic است: `آی سی <PN>`.
- Phase 2 علاوه بر Datasheet، Package/Case فیزیکی را از Mouser، Datasheet4U و ALLDATASHEET (Exact PN only) استخراج می‌کند.
- اگر Package در Phase 2 resolve نشود، Phase 3 هنگام پردازش PDF فقط به‌عنوان fallback آن را استخراج و در Metadata canonical ثبت می‌کند.
- Admin Approval یک Canonical Bundle در `ready_for_upload/<PN>/` می‌سازد. Publisher فقط همین Bundle را مصرف می‌کند و Legacy folder scanning ندارد.
- Publisher V3 از Flow مقاوم V1.5.5 استفاده می‌کند، Category `قطعات الکترونیکی → آی سی` را نیز انتخاب می‌کند و فقط `Save Draft` می‌زند.
- State دقیق Publisher در `runtime_state/publisher/<PN>.json` نگهداری می‌شود و WordPress Product ID مرز ضد Duplicate است.
- UI دارای `Publish` و `Report` است. Publish فقط در حالت idle و وقتی Admin Audit باز نیست فعال می‌شود.
- Report یک Excel روزانه در `reports/YYYY-MM-DD.xlsx` می‌سازد. Phase 4 فقط یک ستون `successful/unsuccessful` دارد؛ شکست هر Step اجباری = unsuccessful.

> V3.1 patch: اگر Package unresolved باشد، محصول همچنان وارد Phase 4 می‌شود؛ فقط ویژگی Part Number ثبت می‌شود و سلول Package در Report قرمز می‌ماند.

## نصب سریع Windows

```cmd
cd C:\PATH\TO\Tavakol_Phase1_Phase2_Phase3_Phase4_Integrated_V3.1
python -m pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
copy proxies.example.txt proxies.txt
python run_ui.py
```

Secrets فقط در `.env` و `proxies.txt` قرار می‌گیرند و نباید Commit شوند. برای Phase 4 تا زمانی که `ALLOW_SITE_WRITE=true` نشده، Publisher فقط Dry Run انجام می‌دهد.

## CLI

```cmd
python run_integrated.py
python run_publisher.py
python run_report.py
```

`run_publisher.py` قبل از باز کردن WordPress، برای محصولات Legacy/مهاجرت‌کرده‌ای که `APPROVED + FINALIZED` هستند و داده‌های لازم برای انتشار را دارند، Canonical Bundle گمشده را می‌سازد. Package unresolved در V3.1 استثناست و مانع Bundle/Publish نمی‌شود. محصولات ناقص را گزارش می‌کند و بقیه Batch را متوقف نمی‌کند.

## State / Data Contract

```text
metadata/<PN>.json                 live canonical product/pipeline truth
runtime_state/...                  execution/resume checkpoints
runtime_state/publisher/<PN>.json detailed Phase 4 checkpoint + anti-duplicate
work/...                           intermediate artifacts
ready_for_upload/<PN>/             approved publication snapshot
  product.json
  product.html
  <PN>.webp
  <PN>.pdf                         only when datasheet status=completed
```

اگر داده‌ی upstream بعد از Approval تغییر کند، Bundle قبلی دیگر authoritative نیست و باید invalidate/re-audit/rebuild شود.

## تست و Validation

```cmd
python -m pytest -q tests_phase2 tests_phase3 tests_v3
python validate_schemas.py
```

---

# Historical V2.1 documentation (retained for lineage)

# Tavakol Electronics — Integrated Phase 1 + Phase 2 + Phase 3 V2.1

این نسخه بر پایه Integrated V2 ساخته شده و چهار تغییر عملی دارد:

1. **حذف کامل مدل گران از مسیر فعال**: OCR پیش‌فرض = Luna با Sol fallback؛ Phase 3 PDF = فقط یک Luna call؛ Writer = فقط Luna + local repairs.
2. **Audit auto-advance پایدار**: Approve/Enter/Confirm Disapprove فقط به آیتم بعدی همان sequence می‌رود و دیگر ناگهان به ابتدای لیست برنمی‌گردد.
3. **`manual_required` یک Gate واقعی است**: تا زمانی که PDF دستی اضافه نشود، Phase 3 برای آن محصول اجرا نمی‌شود.
4. **Manual Datasheet در Audit**: برای `manual_required`، `not_found_confirmed` و `identity_found_unresolved` می‌توان PDF را Drag & Drop کرد یا با Browse انتخاب کرد. فایل به `datasheets/<PN>.pdf` منتقل/کپی، Metadata آپدیت، و Phase 3 برای Run بعدی invalidate/queue می‌شود.

## اجرای سریع در Windows CMD — بدون venv

```cmd
cd C:\PATH\TO\Tavakol_Phase1_Phase2_Phase3_Integrated_V2.1.1
python -m pip install -r requirements.txt
copy .env.example .env
copy proxies.example.txt proxies.txt
python run_ui.py
```

در `.env` کلیدهای OpenAI و Mouser و در `proxies.txt` پروکسی واقعی را قرار دهید.

CLI بدون UI:

```cmd
python run_integrated.py
```

تست Repo:

```cmd
python -m pytest -q tests_phase2 tests_phase3
python validate_schemas.py
```

---

## ورودی عادی — `input/`

تصاویر بدون PN قطعی در `input/` قرار می‌گیرند و Phase 1 به شکل عادی اجرا می‌شود:

```text
Precheck
→ GPT Image LOW
→ Structural Validator
→ MEDIUM fallback only if structural mismatch
→ OCR PartNumber
→ Logo
→ Final WebP
→ Phase 2
→ Phase 3
```

---

## ورودی PN قطعی — `PN_input/`

اگر Part Number را از ابتدا می‌دانید، تصویر را با **نام دقیق PN** در `PN_input/` ذخیره کنید:

```text
PN_input/TC426MJA.jpg
PN_input/TBB1469.png
```

در این مسیر:

- نام فایل Authority برای Part Number است.
- Precheck / Regeneration / Identity Validation طبق معماری عادی اجرا می‌شوند.
- **OCR PartNumber اجرا نمی‌شود.**
- سپس Logo → Final → Phase 2 → Phase 3 ادامه پیدا می‌کند.

Metadata نمونه:

```json
"original_imag": {
  "file": "PN_input/TC426MJA.jpg",
  "source": "PN_input",
  "part_number_authority": "USER_FILENAME",
  "note": "Original image with the confirmed PartNumber filename ... is stored in PN_input; OCR PartNumber extraction was skipped."
}
```

---

# Admin Audit V2.1

دکمه **Audit** به UI اصلی اضافه شده است.

- هنگام اجرای Pipeline: `Audit = disabled`
- وقتی Pipeline متوقف/تمام شده باشد: `Audit = enabled`

با باز کردن Audit، محصولات یکی‌یکی نمایش داده می‌شوند.

### اطلاعات نمایش داده‌شده

- Original Image
- Final Image یا Prepared Image برای آیتم ناقص
- Part Number
- Datasheet Found: YES/NO
- Datasheet status
- نام PDF دیتاشیت
- SEO score
- SEO status / disposition
- Keyword density + target
- Word count + target
- Structure pass
- Fact safety pass
- Semantic audit status
- Tone status / naturalness

### رنگ وضعیت

- **AUDIT NEEDED** — قرمز: حداقل یکی از خروجی‌های لازم کامل نیست یا PN/Phase 1 مشکل دارد.
- **FINALIZED** — سبز: Final image + Phase 2 terminal result + Phase 3 output + `products/PART_NUMBER.json` موجود است و آماده چک انسانی است.

---

## Approve

برای محصول `FINALIZED`، Admin می‌تواند `Approve` را بزند.

پس از Approve:

```text
status.admin_approved = true
admin_audit.status = APPROVED
```

و Bundle آماده آپلود ساخته می‌شود:

```text
ready_for_upload/PART_NUMBER/
    PART_NUMBER.webp
    metadata_PART_NUMBER.json
    seo_PART_NUMBER.json
    PART_NUMBER.html
    product_PART_NUMBER.json       (اگر integrated product موجود باشد)
    PART_NUMBER.pdf                (اگر دیتاشیت موجود باشد)
    upload_manifest.json
```

V1.2 هنوز مستقیماً به WordPress ارسال نمی‌کند؛ این پوشه مرز نهایی قبل از Publishing Adapter است.

---

## Disapprove

Admin می‌تواند یک یا چند دلیل را انتخاب کند:

- `wrong part number`
- `image regeneration needed`
- `wrong data sheet`
- `SEO content regeneration needed`

تصمیم فوراً در Checkpoint ذخیره می‌شود. Reprocess API داخل پنجره Audit اجرا نمی‌شود؛ آیتم برای **Run بعدی با Start** آماده می‌شود تا تمام Error Recovery / Checkpoint rules استاندارد حفظ شوند.

### Wrong Part Number

با انتخاب `wrong part number`:

- `wrong data sheet` غیرفعال می‌شود.
- `SEO content regeneration needed` غیرفعال می‌شود.
- یک Entry دقیقاً کنار همان گزینه باز می‌شود:

```text
enter the right PN: [____________]
```

`image regeneration needed` همچنان می‌تواند هم‌زمان انتخاب شود.

بعد از ثبت PN صحیح:

1. Metadata canonical به PN جدید rename می‌شود.
2. Final image در صورت معتبر بودن به PN جدید rename می‌شود.
3. Runtime state به PN جدید اصلاح می‌شود.
4. Datasheet قبلی و technical caches مرتبط با PN غلط از active pipeline خارج و در `audit_history/` نگهداری می‌شوند.
5. Phase 2 برای PN صحیح دوباره اجرا می‌شود.
6. Phase 3 طبق نتیجه Phase 2 دوباره اجرا می‌شود.

OCR برای PN واردشده توسط Admin دوباره اجرا نمی‌شود؛ Authority آن `ADMIN_AUDIT_ENTERED_PART_NUMBER` است.

### استثنای No-Datasheet → No-Datasheet

فقط در این حالت:

```text
PN غلط: Phase 2 = NOT_FOUND_CONFIRMED
↓ Admin PN را اصلاح می‌کند
PN صحیح: Phase 2 = NOT_FOUND_CONFIRMED
```

Phase 3 API دوباره Trigger نمی‌شود.

سیستم نسخه SEO قبلی را از `audit_history` می‌گیرد و **تمام occurrenceهای PN غلط را programmatically با PN صحیح جایگزین می‌کند**، فایل JSON/HTML را با PN جدید صادر می‌کند و محصول را `READY_FOR_REAUDIT` می‌کند.

اگر PN صحیح Datasheet پیدا کند یا هر حالت دیگری رخ دهد، Phase 3 طبق معماری عادی از نو اجرا می‌شود.

### Image Regeneration Needed

فقط بخش تصویر invalidate می‌شود:

```text
Regeneration
→ Identity Validation
→ Logo
→ Final WebP
```

اگر فقط همین گزینه انتخاب شده باشد، Phase 2/3 دوباره اجرا نمی‌شوند.

### Wrong Data Sheet

- PDF قبلی از active datasheets خارج و در `audit_history/` آرشیو می‌شود.
- Phase 2 از صفر برای همان PN اجرا می‌شود.
- Fact Extraction و Phase 3 نیز با `force_fact_extraction` و `force` دوباره اجرا می‌شوند.

### SEO Content Regeneration Needed

- Phase 1 و Phase 2 دست‌نخورده می‌مانند.
- فقط Phase 3 content pipeline دوباره اجرا می‌شود.

---

## حذف `audit needed/` قدیمی

Feature پوشه `audit needed/` متعلق به V1.1 در V1.2 حذف شده است.

برای آیتم‌های مشکل‌دار V1.1 کافی است `metadata/ + output/ + input/` قبلی را منتقل کنید. Audit UI آن‌ها را با عنوان قرمز **AUDIT NEEDED** نشان می‌دهد و PN را همان‌جا وارد می‌کنید.

---

## Orchestrator Streaming

```text
Phase 1 PN ready
   └──> Phase 2 immediately
          └──> terminal datasheet decision
                 └──> Phase 3 immediately
```

Phase 1 sequential است؛ Phase 2 و Phase 3 worker مستقل دارند و محصولات مختلف می‌توانند در فازهای متفاوت هم‌زمان جلو بروند.

---

## پوشه‌های Runtime مهم

```text
input/                 ورودی عادی
PN_input/              ورودی با PN قطعی؛ OCR PN skip
output/                فایل‌های میانی Phase 1
Final/                 WebP نهایی
metadata/              canonical Phase 1+2 checkpoint + Admin Audit state
datasheets/            PDFهای Phase 2
phase3_outputs/         JSON + HTML فاز 3
products/               Integrated product JSON
work/                   Phase 3 checkpoints
runtime_state/          Orchestrator checkpoints
ready_for_upload/       محصولات Admin-approved آماده Publishing
audit_history/          Snapshot/آرشیو artifactهای invalidate شده توسط Admin
logs/                   لاگ‌ها
```

---

# Migration از Integrated V1.1 به V1.2

برای Resume کامل این پوشه‌ها را از V1.1 به V1.2 منتقل کنید:

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

همچنین فایل‌های واقعی تنظیمات را منتقل کنید:

```text
.env
proxies.txt
```

اختیاری:

```text
logs/
debug_html/
seo/
```

**`audit needed/` را منتقل نکنید.** این Feature در V1.2 حذف شده است.

پوشه‌های جدید `PN_input/`, `ready_for_upload/`, `audit_history/` از قبل در Repo وجود دارند و بهتر است از نسخه V1.2 استفاده شوند.

V1.2 همان recovery مربوط به stale `image_optimized=false` در V1.0/V1.1 را حفظ می‌کند؛ بنابراین `metadata/` را همیشه همراه `Final/` منتقل کنید تا Finalهای قبلی دوباره API مصرف نکنند.

---

## امنیت

`.env` و `proxies.txt` در Git ignore هستند. Credential واقعی داخل Repo قرار نگرفته است.

---

## V2.1 — سیاست مدل و هزینه

```text
Phase 1 OCR: GPT-5.6 Luna → GPT-5.6 Sol fallback only when OCR is uncertain
Phase 3 PDF: GPT-5.6 Luna exactly once (first up to 5 pages)
Phase 3 Writer: GPT-5.6 Luna, maximum 2 cheap attempts
Tone Editor: GPT-5.4-mini
Final facts-only audit: GPT-5.4-mini
Expensive PDF/Writer tier: DISABLED
```

اگر 5 صفحه اول Fact کافی ندهند، سیستم همان Factهای امن را نگه می‌دارد و Coverage را `SPARSE`/`INSUFFICIENT` گزارش می‌کند؛ **هیچ PDF model call دوم انجام نمی‌شود**.

## V2.1 — Manual Datasheet Gate

اگر Phase 2 به `manual_required` برسد:

```text
Phase 2 = MANUAL_REQUIRED
Phase 3 = BLOCKED_MANUAL_DATASHEET
```

در Audit همان محصول یک Drop Zone نمایش داده می‌شود. PDF صحیح را روی آن رها کنید یا `Browse PDF` را بزنید. پس از ثبت:

```text
datasheets/<PART_NUMBER>.pdf
metadata.datasheet.status = completed
metadata.datasheet.document_source = ADMIN_AUDIT_MANUAL
force_phase3 = true
force_fact_extraction = true
```

سپس در Start بعدی Phase 3 با PDF دستی اجرا می‌شود.
