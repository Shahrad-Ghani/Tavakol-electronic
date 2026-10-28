import json
from pathlib import Path

from phase3_final.pipeline import Phase3FinalPipeline
from phase3_final.internal_link_policy import select_anchor

ROOT=Path(__file__).resolve().parents[1]

class FakeContentAgent:
    model='gpt-5.6-luna'
    def __init__(self, body, pn): self.body=body; self.pn=pn
    def _raw(self, body):
        return {
            'seo_title':f'خرید آی سی {self.pn} | قیمت و موجودی',
            'meta_description':f'خرید {self.pn} با استعلام قیمت و موجودی، فروش تکی و تعدادی و ضمانت اصالت کالا از توکل الکترونیک.',
            'body_markdown':body,
            'image_alts':[{'filename':f'{self.pn}.webp','alt':f'آی سی {self.pn}'}],
            'internal_links':[], 'external_links':[],
            'woocommerce_attributes':{'part_number':self.pn,'package_installation':'نیازمند تأیید'},
        }
    def generate(self, instructions, user_input):
        return self._raw(self.body), {'provider':'openai','model':self.model,'usage':{'input_tokens':100,'output_tokens':100}}
    def repair_body(self, instructions, user_input):
        return {'body_markdown':self.body}, {'provider':'openai','model':self.model,'usage':{'input_tokens':50,'output_tokens':50}}

class FakeTone:
    def __init__(self, body): self.body=body
    def edit(self, **kw):
        return {'status':'UNCHANGED','naturalness_score':90,'ai_like_style_score':10,'flags':[],'technical_facts_changed':False,'body_markdown':kw['body_markdown'],'changes':[{'action':'KEEP','reason':'already natural'}]}, {'provider':'openai','model':'gpt-5.4-mini','usage':{'input_tokens':50,'output_tokens':20}}

class FakeAuditor:
    def audit(self, **kw):
        assert 'pdf_path' not in kw
        return {'status':'PASS','wrong_values':[],'wrong_units':[],'wrong_conditions':[],'variant_leakage':[],'unsupported_technical_claims':[],'absolute_max_as_operating':[],'reason':'facts-only pass'}, {'provider':'openai','model':'gpt-5.4-mini','usage':{'input_tokens':50,'output_tokens':20}}


def make_body(pn, anchor):
    return f'''{pn} برای استعلام قیمت و تهیه قطعه با کد دقیق استفاده می‌شود. برای مشاهده مدل‌های دیگر می‌توانید {anchor} را هم بررسی کنید. سفارش این قطعه به‌صورت تکی و تعدادی امکان‌پذیر است و ضمانت اصالت کالا مطابق شرایط فروشگاه ارائه می‌شود.

## **معرفی {pn}**
### **انتخاب {pn} برای سفارش**
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


def test_end_to_end_commercial_mock_writes_altimate_schema_and_scorecard(tmp_path):
    pn='TC427CPA'
    anchor=select_anchor(ROOT,pn,'IC')['anchor']
    body=make_body(pn,anchor)
    fixture=ROOT/'tests_phase3'/'fixtures'/'TC427CPA.json'
    product=json.loads(fixture.read_text(encoding='utf-8'))
    product['source']={
        'datasheet_status':'NO_FULL_DATASHEET','datasheet_path':None,'model_pdf_path':None,'pdf_window':None,
        'source_validation':'NO_FILE','fact_status':'NOT_RUN','useful_fact_count':0,'facts_path':None,
        'primary_extraction_path':None,'fallback_extraction_path':None,'coverage_path':None,'pdf_calls':0,
        'pdf_fallback_used':False,'priority_fact_coverage':None,
    }
    agent=FakeContentAgent(body,pn)
    pipe=Phase3FinalPipeline(ROOT,cheap_agent=agent,expensive_agent=agent,tone_editor=FakeTone(body),final_auditor=FakeAuditor())
    pipe.cfg['seo_threshold']=0
    pipe.cfg['keyword_density_target']={'min':0.0,'max':10.0}
    pipe.cfg['commercial_target_words']={'min':100,'preferred_min':150,'max':400}
    result=pipe.process_product(product,fixture,tmp_path,force=True)
    state=json.loads(Path(result['final_path']).read_text(encoding='utf-8'))
    assert state['schema_version']=='phase3-altimate-product-v1'
    assert state['page']['product_title'] == f'آی سی {pn}'
    assert state['validation']['final_semantic_audit']['status']=='PASS'
    assert state['validation']['final_semantic_audit_history'][0]['pdf_access']=='CLOSED'
    assert state['evaluation_scorecard']['quality_metric_policy']=='PASS_RATE_IS_OPERATIONAL_ONLY_NOT_PRIMARY_QUALITY_METRIC'
    assert state['content'].get('body_markdown')
    assert 'markdown_path' not in state['content']
    assert not list(tmp_path.rglob('*.md'))
