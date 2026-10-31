import json
from pathlib import Path

from jsonschema import Draft202012Validator

from core.category_registry import category_context
from phase3_final.fact_safety import validate_fact_safety
from phase3_final.internal_link_policy import select_anchor
from phase3_final.pipeline import Phase3FinalPipeline
from phase3_final.prompt_builder import build_user_payload

ROOT = Path(__file__).resolve().parents[1]


def test_to_package_less_specific_claim_is_supported_by_more_specific_verified_identity():
    out = validate_fact_safety(
        'این قطعه در پکیج TO-92 عرضه می‌شود.',
        None,
        'TECHNICAL_LIGHT',
        verified_identity={'verified_package_installation': 'TO-92 3L'},
    )
    assert out['passed'] is True, out


def test_to_package_conflict_is_still_rejected():
    out = validate_fact_safety(
        'این قطعه در پکیج TO-220 عرضه می‌شود.',
        None,
        'TECHNICAL_LIGHT',
        verified_identity={'verified_package_installation': 'TO-92 3L'},
    )
    assert out['passed'] is False
    assert out['failures'][0]['code'] == 'UNSUPPORTED_PACKAGE_CLAIM'


def test_more_specific_to_claim_is_not_invented_from_generic_verified_identity():
    out = validate_fact_safety(
        'این قطعه در پکیج TO-92 3L عرضه می‌شود.',
        None,
        'TECHNICAL_LIGHT',
        verified_identity={'verified_package_installation': 'TO-92'},
    )
    assert out['passed'] is False


def test_fact_safety_repair_payload_explicitly_contains_original_content_and_errors(tmp_path):
    product = {
        'identity': {'part_number': 'X1', 'manufacturer': None, 'product_type_label': 'آی سی', 'product_category': 'ic', 'verified_package_installation': None},
        'source': {'facts_path': None, 'fact_status': 'NOT_RUN', 'useful_fact_count': 0, 'priority_fact_coverage': None, 'pdf_fallback_used': False},
        'images': [],
        'seo_context': {'approved_external_links': []},
    }
    text = build_user_payload(
        tmp_path/'input.json', product, 'COMMERCIAL_ONLY', {},
        fact_safety_repair={
            'original_content': 'محتوای اولیه با ادعای اشتباه',
            'errors': [{'code': 'UNSUPPORTED_TECHNICAL_CLAIM', 'claim': '500 V'}],
        },
    )
    payload = json.loads(text.split('\n', 1)[1])
    ctx = payload['FACT_SAFETY_REPAIR_CONTEXT']
    assert ctx['ORIGINAL_GENERATED_CONTENT'] == 'محتوای اولیه با ادعای اشتباه'
    assert ctx['FACT_SAFETY_ERRORS'][0]['claim'] == '500 V'
    assert 'Do not add new technical facts' in ctx['REPAIR_INSTRUCTION']


def test_integrated_identity_schema_accepts_strict_category_context():
    schema = json.loads((ROOT/'schema'/'integrated_product.schema.json').read_text(encoding='utf-8'))
    identity_schema = schema['properties']['identity']
    identity = {
        'part_number': 'IRF3205',
        'manufacturer': None,
        'manufacturer_country': None,
        'category': 'mosfet',
        'category_context': category_context('mosfet'),
        'package': {
            'value': None,
            'status': 'UNKNOWN',
            'phase2_mouser': None,
            'phase3_datasheet': None,
        },
    }
    errors = list(Draft202012Validator(identity_schema).iter_errors(identity))
    assert errors == [], [e.message for e in errors]


class RepairAwareAgent:
    model = 'gpt-5.6-luna'
    def __init__(self, unsafe_body, safe_body, pn):
        self.unsafe_body = unsafe_body
        self.safe_body = safe_body
        self.pn = pn
        self.repair_calls = []

    def _raw(self, body):
        return {
            'seo_title': f'خرید آی سی {self.pn} | قیمت و موجودی',
            'meta_description': f'برای خرید {self.pn} قیمت و موجودی را بررسی کنید.',
            'body_markdown': body,
            'image_alts': [{'filename': f'{self.pn}.webp', 'alt': f'آی سی {self.pn}'}],
            'internal_links': [], 'external_links': [],
            'woocommerce_attributes': {'part_number': self.pn, 'package_installation': 'نیازمند تأیید'},
        }

    def generate(self, instructions, user_input):
        return self._raw(self.unsafe_body), {'provider':'openai','model':self.model,'usage':{'input_tokens':10,'output_tokens':10}}

    def repair_body(self, instructions, user_input):
        self.repair_calls.append((instructions, user_input))
        # Keep the first generic retry unsafe. Only the explicit V4.0.1
        # Fact-Safety prompt fixes the claim, proving the dedicated pass runs.
        body = self.safe_body if 'FACT SAFETY TARGETED REPAIR' in instructions else self.unsafe_body
        return {'body_markdown': body}, {'provider':'openai','model':self.model,'usage':{'input_tokens':10,'output_tokens':10}}


class PassTone:
    def edit(self, **kw):
        return {
            'status':'UNCHANGED','naturalness_score':90,'ai_like_style_score':10,
            'flags':[],'technical_facts_changed':False,'body_markdown':kw['body_markdown'],
            'changes':[{'action':'KEEP','reason':'ok'}],
        }, {'provider':'openai','model':'gpt-5.4-mini','usage':{'input_tokens':10,'output_tokens':10}}


class PassAuditor:
    def audit(self, **kw):
        return {
            'status':'PASS','wrong_values':[],'wrong_units':[],'wrong_conditions':[],
            'variant_leakage':[],'unsupported_technical_claims':[],
            'absolute_max_as_operating':[],'reason':'pass',
        }, {'provider':'openai','model':'gpt-5.4-mini','usage':{'input_tokens':10,'output_tokens':10}}


def _body(pn, anchor, unsafe=False):
    extra = ' این قطعه در پکیج TO-220 عرضه می‌شود.' if unsafe else ''
    return f'''{pn} برای استعلام قیمت و تهیه قطعه با کد دقیق استفاده می‌شود.{extra} برای مشاهده مدل‌های دیگر می‌توانید {anchor} را هم بررسی کنید. سفارش تکی و تعدادی امکان‌پذیر است.

## **معرفی {pn}**
### **انتخاب {pn} برای سفارش**
پیش از ثبت سفارش، پارت‌نامبر را با فهرست خرید خود تطبیق دهید. در نبود دیتاشیت معتبر، مشخصات فنی حدس زده نمی‌شود.

| مورد | توضیح |
|---|---|
| پارت‌نامبر | {pn} |
| وضعیت قیمت | نیازمند استعلام روز |

---

## **خرید و قیمت {pn}**
برای دریافت قیمت و موجودی روز، تعداد موردنیاز را اعلام کنید. امکان فروش تکی، تعدادی و دریافت پیش‌فاکتور وجود دارد.

---

## **سوالات متداول**
### **چطور {pn} را سفارش دهم؟**
پارت‌نامبر و تعداد موردنیاز را برای استعلام ارسال کنید.

### **آیا مشخصات فنی این قطعه قطعی است؟**
بدون منبع معتبر، مشخصات فنی حدس زده نمی‌شود.

---

## **جمع‌بندی و سفارش {pn}**
برای استعلام نهایی قیمت، موجودی و ثبت سفارش با توکل الکترونیک تماس بگیرید.'''


def test_pipeline_runs_explicit_fact_safety_repair_when_generic_retry_still_unsafe(tmp_path):
    pn = 'TC427CPA'
    fixture = ROOT/'tests_phase3'/'fixtures'/'TC427CPA.json'
    product = json.loads(fixture.read_text(encoding='utf-8'))
    product['identity']['product_category'] = 'ic'
    product['source'] = {
        'datasheet_status':'NO_FULL_DATASHEET','datasheet_path':None,'model_pdf_path':None,'pdf_window':None,
        'source_validation':'NO_FILE','fact_status':'NOT_RUN','useful_fact_count':0,'facts_path':None,
        'primary_extraction_path':None,'fallback_extraction_path':None,'coverage_path':None,'pdf_calls':0,
        'pdf_fallback_used':False,'priority_fact_coverage':None,
    }
    anchor = select_anchor(ROOT, pn, 'ic')['anchor']
    unsafe = _body(pn, anchor, unsafe=True)
    safe = _body(pn, anchor, unsafe=False)
    agent = RepairAwareAgent(unsafe, safe, pn)
    pipe = Phase3FinalPipeline(ROOT, cheap_agent=agent, tone_editor=PassTone(), final_auditor=PassAuditor())
    pipe.cfg['seo_threshold'] = 0
    pipe.cfg['keyword_density_target'] = {'min':0.0,'max':10.0}
    pipe.cfg['commercial_target_words'] = {'min':100,'preferred_min':150,'max':500}
    pipe.cfg['fact_safety_repair_max_attempts'] = 1
    result = pipe.process_product(product, fixture, tmp_path, force=True)
    state = json.loads(Path(result['final_path']).read_text(encoding='utf-8'))
    assert state['generation']['fact_safety_repair_attempts_used'] == 1
    assert any('FACT SAFETY TARGETED REPAIR' in x[0] for x in agent.repair_calls)
    repair_call = next(x for x in agent.repair_calls if 'FACT SAFETY TARGETED REPAIR' in x[0])
    assert 'FACT_SAFETY_REPAIR_CONTEXT' in repair_call[1]
    assert 'DIP-8' in repair_call[1]
    assert state['validation']['fact_safety']['passed'] is True
