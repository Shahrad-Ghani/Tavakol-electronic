import json
from pathlib import Path
from phase3_final.model_router import expensive_escalation_decision
from phase3_final.evaluation_scorecard import aggregate_batch_scorecard

ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config'/'phase3_final.json').read_text(encoding='utf-8'))


def test_model_cost_router_is_v21_luna_only():
    assert CFG['pdf_primary_model']=='gpt-5.6-luna'
    assert CFG['pdf_fallback_model']=='gpt-5.6-luna'  # compatibility alias; active fallback is disabled
    assert CFG['pdf_max_calls_per_product']==1
    assert CFG['cheap_writer_model']=='gpt-5.6-luna'
    assert CFG['expensive_writer_model']=='gpt-5.6-luna'
    assert CFG['expensive_writer_max_attempts']==0
    assert 'gpt-5.6-terra' not in CFG.get('model_pricing_per_1m_usd',{})
    assert CFG['tone_editor_model']=='gpt-5.4-mini'
    assert CFG['facts_auditor_model']=='gpt-5.4-mini'


def test_expensive_writer_router_is_disabled_in_v21():
    attempts=[
        {'model_tier':'CHEAP','hard_gate_pass':True,'fact_safety_pass':True,'contract_pass':False,'score':55},
        {'model_tier':'CHEAP','hard_gate_pass':True,'fact_safety_pass':True,'contract_pass':False,'score':58},
    ]
    route=expensive_escalation_decision(attempts,cutoff=60)
    assert route['escalate'] is False
    assert route['reason']=='EXPENSIVE_MODEL_DISABLED_V2.1'


def test_fact_prompt_priorities_are_hints_not_whitelist():
    p=(ROOT/'prompts'/'altimate_v1'/'fact_extractor_primary.md').read_text(encoding='utf-8')
    assert 'NOT a whitelist' in p
    assert 'switching time' in p
    assert 'voltage / voltage rating / operating supply voltage' in p


def test_writer_and_tone_prompts_explicitly_reject_ai_like_meta_tone():
    w=(ROOT/'prompts'/'shared_system.md').read_text(encoding='utf-8')
    t=(ROOT/'prompts'/'altimate_v1'/'tone_editor.md').read_text(encoding='utf-8')
    assert 'در این صفحه' in w
    assert 'گزارش AI' in t
    assert 'Fact' in t


def test_batch_scorecard_marks_pass_rate_as_operational_only():
    items=[
        {'status':'PASS','scorecard':{'fact_extraction':{'pdf_calls':1,'priority_coverage_pct':50,'pdf_fallback_used':False},'seo':{'score':82},'cost_and_escalation':{'estimated_total_cost_usd':0.01,'pdf_calls':1,'pdf_fallback_used':False,'expensive_writer_used':False}}},
        {'status':'REVIEW_REQUIRED','scorecard':{'fact_extraction':{'pdf_calls':2,'priority_coverage_pct':80,'pdf_fallback_used':True},'seo':{'score':80},'cost_and_escalation':{'estimated_total_cost_usd':0.02,'pdf_calls':2,'pdf_fallback_used':True,'expensive_writer_used':False}}},
    ]
    s=aggregate_batch_scorecard(items)
    assert s['operational_pass_rate_pct']==50.0
    assert s['quality_metric_policy']=='PASS_RATE_IS_OPERATIONAL_ONLY_NOT_PRIMARY_QUALITY_METRIC'
    assert s['average_pdf_calls_per_technical_product']==1.5
    assert s['pdf_fallback_rate_pct']==50.0
