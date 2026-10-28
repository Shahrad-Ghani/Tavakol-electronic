import json
from pathlib import Path

from phase3_final.deterministic_repairs import ensure_intro_heading, intro_heading_status
from phase3_final.html_renderer import render_html
from phase3_final.internal_link_policy import select_anchor
from phase3_final.pipeline import Phase3FinalPipeline

ROOT = Path(__file__).resolve().parents[1]


def _product(pn='2N4093', label='ماسفت', category='mosfet'):
    return {
        'identity': {
            'part_number': pn,
            'manufacturer': 'Example',
            'product_type_label': label,
            'product_category': category,
            'verified_package_installation': 'TO-18',
        }
    }


def test_missing_intro_h2_is_inserted_category_aware_before_existing_intro_paragraphs():
    product = _product()
    body = (
        'JFET 2N4093 یک قطعه کانال N برای کاربردهای سوئیچینگ است.\n\n'
        'پکیج و مشخصات باید پیش از سفارش بررسی شوند.\n\n'
        '---\n\n'
        '## **مشخصات فنی ماسفت 2N4093**\n\n'
        'متن مشخصات.'
    )
    repaired, record, repairs = ensure_intro_heading(product, body)
    assert repaired.startswith('## **معرفی ماسفت 2N4093**\n\nJFET 2N4093')
    assert record['status'] == 'PASS'
    assert record['found'] is True
    assert record['programmatic_repair_applied'] is True
    assert repairs == ['intro_header_programmatic_v4_0_4']


def test_existing_natural_intro_h2_is_accepted_without_rewrite():
    product = _product(pn='2N6660')
    body = '## **معرفی ماسفت 2N6660**\n\nمتن معرفی.\n\n## **مشخصات فنی 2N6660**\n\nمتن.'
    repaired, record, repairs = ensure_intro_heading(product, body)
    assert repaired == body + '\n'
    assert record['found'] is True
    assert record['occurrences'] == 1
    assert record['programmatic_repair_applied'] is False
    assert repairs == []


def test_intro_header_repair_is_idempotent_and_html_renderer_emits_h2():
    product = _product()
    body = 'متن معرفی 2N4093.\n\n## **مشخصات فنی 2N4093**\n\nمتن.'
    once, record1, _ = ensure_intro_heading(product, body)
    twice, record2, repairs2 = ensure_intro_heading(product, once)
    assert once == twice
    assert record1['programmatic_repair_applied'] is True
    assert record2['programmatic_repair_applied'] is False
    assert repairs2 == []
    html = render_html(once)
    assert '<h2' in html
    assert '<strong>معرفی ماسفت 2N4093</strong>' in html


class _FakeAgent:
    model = 'gpt-5.6-luna'
    def __init__(self, body, pn):
        self.body = body
        self.pn = pn
    def _raw(self, body):
        return {
            'seo_title': f'خرید آی سی {self.pn} | قیمت و موجودی',
            'meta_description': f'برای خرید {self.pn} قیمت و موجودی را بررسی کنید.',
            'body_markdown': body,
            'image_alts': [{'filename': f'{self.pn}.webp', 'alt': f'آی سی {self.pn}'}],
            'internal_links': [],
            'external_links': [],
            'woocommerce_attributes': {'part_number': self.pn, 'package_installation': 'نیازمند تأیید'},
        }
    def generate(self, instructions, user_input):
        return self._raw(self.body), {'provider': 'openai', 'model': self.model, 'usage': {'input_tokens': 10, 'output_tokens': 10}}
    def repair_body(self, instructions, user_input):
        return {'body_markdown': self.body}, {'provider': 'openai', 'model': self.model, 'usage': {'input_tokens': 10, 'output_tokens': 10}}


class _FakeTone:
    def edit(self, **kw):
        return {
            'status': 'UNCHANGED', 'naturalness_score': 90, 'ai_like_style_score': 10,
            'flags': [], 'technical_facts_changed': False,
            'body_markdown': kw['body_markdown'], 'changes': [{'action': 'KEEP', 'reason': 'ok'}],
        }, {'provider': 'openai', 'model': 'gpt-5.4-mini', 'usage': {'input_tokens': 10, 'output_tokens': 10}}


class _FakeAuditor:
    def audit(self, **kw):
        return {
            'status': 'PASS', 'wrong_values': [], 'wrong_units': [], 'wrong_conditions': [],
            'variant_leakage': [], 'unsupported_technical_claims': [], 'absolute_max_as_operating': [],
            'reason': 'pass',
        }, {'provider': 'openai', 'model': 'gpt-5.4-mini', 'usage': {'input_tokens': 10, 'output_tokens': 10}}


def _body_without_intro_header(pn, anchor):
    return f'''{pn} برای استعلام قیمت و تهیه قطعه با کد دقیق استفاده می‌شود. برای مشاهده مدل‌های دیگر می‌توانید {anchor} را هم بررسی کنید. سفارش این قطعه به‌صورت تکی و تعدادی امکان‌پذیر است و ضمانت اصالت کالا مطابق شرایط فروشگاه ارائه می‌شود.

پیش از ثبت سفارش، پارت‌نامبر را با فهرست خرید خود تطبیق دهید. در نبود دیتاشیت معتبر، مشخصات فنی حدس زده نمی‌شود و استعلام بر اساس کد دقیق قطعه انجام می‌شود.

| مورد | توضیح |
|---|---|
| پارت‌نامبر | {pn} |
| وضعیت قیمت | نیازمند استعلام روز |

---

## **خرید و قیمت {pn}**
برای دریافت قیمت و موجودی روز، تعداد موردنیاز را اعلام کنید. امکان فروش تکی، تعدادی، خرید عمده و دریافت پیش‌فاکتور وجود دارد.

---

## **سوالات متداول**
### **چطور {pn} را سفارش دهم؟**
پارت‌نامبر و تعداد موردنیاز را برای استعلام ارسال کنید تا وضعیت موجودی و قیمت بررسی شود.

### **آیا مشخصات فنی این قطعه قطعی است؟**
در این حالت مشخصات فنی بدون منبع معتبر اعلام نمی‌شود و فقط اطلاعات فروشگاهی قطعی استفاده می‌شود.

---

## **جمع‌بندی و سفارش {pn}**
برای استعلام نهایی قیمت، موجودی و ثبت سفارش با توکل الکترونیک تماس بگیرید.'''


def test_pipeline_records_intro_repair_and_exports_html(tmp_path):
    pn = 'TC427CPA'
    fixture = ROOT / 'tests_phase3' / 'fixtures' / 'TC427CPA.json'
    product = json.loads(fixture.read_text(encoding='utf-8'))
    product['source'] = {
        'datasheet_status': 'NO_FULL_DATASHEET', 'datasheet_path': None, 'model_pdf_path': None, 'pdf_window': None,
        'source_validation': 'NO_FILE', 'fact_status': 'NOT_RUN', 'useful_fact_count': 0, 'facts_path': None,
        'primary_extraction_path': None, 'fallback_extraction_path': None, 'coverage_path': None, 'pdf_calls': 0,
        'pdf_fallback_used': False, 'priority_fact_coverage': None,
    }
    anchor = select_anchor(ROOT, pn, 'IC')['anchor']
    body = _body_without_intro_header(pn, anchor)
    agent = _FakeAgent(body, pn)
    pipe = Phase3FinalPipeline(ROOT, cheap_agent=agent, expensive_agent=agent, tone_editor=_FakeTone(), final_auditor=_FakeAuditor())
    pipe.cfg['seo_threshold'] = 0
    pipe.cfg['keyword_density_target'] = {'min': 0.0, 'max': 10.0}
    pipe.cfg['commercial_target_words'] = {'min': 100, 'preferred_min': 150, 'max': 500}
    result = pipe.process_product(product, fixture, tmp_path, force=True)
    state = json.loads(Path(result['final_path']).read_text(encoding='utf-8'))
    intro = state['validation']['intro_heading']
    assert intro['status'] == 'PASS'
    assert intro['programmatic_repair_applied'] is True
    assert state['content']['body_markdown'].startswith(f'## **معرفی آی سی {pn}**')
    html = Path(result['html_path']).read_text(encoding='utf-8')
    assert f'<strong>معرفی آی سی {pn}</strong>' in html
