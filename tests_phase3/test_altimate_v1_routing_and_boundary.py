import inspect
from pathlib import Path
from phase3_final.router import choose_mode
from phase3_final.final_auditor import FactsOnlySemanticAuditor

ROOT=Path(__file__).resolve().parents[1]


def test_sparse_final_facts_still_route_to_technical_content():
    p={'source':{'datasheet_status':'FULL_DATASHEET','facts_path':'x.json','useful_fact_count':1,'fact_status':'INSUFFICIENT'}}
    assert choose_mode(p)=='TECHNICAL_LIGHT'


def test_zero_facts_do_not_force_fake_technical_content():
    p={'source':{'datasheet_status':'FULL_DATASHEET','facts_path':None,'useful_fact_count':0,'fact_status':'NOT_RUN'}}
    assert choose_mode(p)=='SALES_ONLY_INSUFFICIENT_FACTS'


def test_final_auditor_signature_has_no_pdf_argument():
    sig=inspect.signature(FactsOnlySemanticAuditor.audit)
    assert 'pdf_path' not in sig.parameters
    assert 'pdf_window' not in sig.parameters


def test_active_runtime_contains_no_pdf_verifier_or_pdf_final_audit():
    active=[ROOT/'integrated_pipeline.py',ROOT/'phase3_fact_extraction'/'pipeline.py',ROOT/'phase3_final'/'pipeline.py',ROOT/'phase3_final'/'final_auditor.py']
    text='\n'.join(p.read_text(encoding='utf-8') for p in active)
    assert 'native_pdf_verifier' not in text
    assert 'Final PDF Auditor' not in text
    assert 'pdf_agent' not in text


def test_prompt_contract_closes_pdf_after_final_facts():
    writer=(ROOT/'prompts'/'shared_system.md').read_text(encoding='utf-8')
    auditor=(ROOT/'prompts'/'altimate_v1'/'facts_only_auditor.md').read_text(encoding='utf-8')
    assert 'PDF برای تو بسته است' in writer
    assert 'PDF در این مرحله عمداً در دسترس نیست' in auditor
