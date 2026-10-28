from pathlib import Path

from phase3_final.pipeline import Phase3FinalPipeline
from phase3_final.fact_safety import validate_fact_safety, _ascii


def _candidate(*, failures, score=79, hard=True, facts=True, style=True):
    return {
        'hard_gate_pass': hard,
        'fact_safety_pass': facts,
        'contract_pass': not failures,
        'score': score,
        'structure': {'failures': list(failures)},
        'style_prefilter': {'passed': style},
    }


def test_seo_density_failure_does_not_block_tone_or_publication_core_gate():
    c = _candidate(failures=['keyword_density_not_severely_outside_target'], score=79)
    assert Phase3FinalPipeline._editorial_ready(c) is True
    assert Phase3FinalPipeline._core_contract_pass(c) is True
    assert Phase3FinalPipeline._publication_ready(c, tone_pass=True, semantic_pass=True) is True


def test_word_count_metric_failure_is_editorial_not_structural_hard_gate():
    c = _candidate(failures=['word_count_not_severely_outside_target'], score=77)
    assert Phase3FinalPipeline._editorial_ready(c) is True


def test_real_structure_failure_still_blocks_tone():
    c = _candidate(failures=['internal_policy_link_exact'], score=90)
    assert Phase3FinalPipeline._editorial_ready(c) is False


def test_hard_gate_or_fact_safety_still_absolute():
    assert Phase3FinalPipeline._editorial_ready(_candidate(failures=[], hard=False)) is False
    assert Phase3FinalPipeline._editorial_ready(_candidate(failures=[], facts=False)) is False


def test_tone_candidate_ok_ignores_seo_79_and_density_only_failure():
    pipe = Phase3FinalPipeline.__new__(Phase3FinalPipeline)
    pipe.cfg = {'tone_naturalness_minimum': 80}
    evaluated = _candidate(failures=['keyword_density_not_severely_outside_target'], score=79)
    tone = {'status': 'PASS', 'technical_facts_changed': False, 'naturalness_score': 90}
    assert pipe._tone_candidate_ok(tone, evaluated, threshold=80) is True


def test_rtl_postfix_minus_normalizes_to_leading_minus_for_fact_safety():
    facts = {
        'part_number': 'TC40H245P',
        'seo_ready_facts': [{
            'id': 'f1',
            'parameter': 'Output current',
            'claim': 'Output current minimum = -0.88 mA',
            'value_text': '-0.88',
            'unit': 'mA',
            'condition': None,
            'section': 'ELECTRICAL_CHARACTERISTIC',
            'scope': 'TARGET_ONLY',
            'seo_usage': 'NORMAL',
        }],
        'limit_only_facts': [],
    }
    result = validate_fact_safety('مقدار حداقل ۰٫۸۸- mA است.', facts, 'TECHNICAL_LIGHT')
    assert result['passed'] is True, result


def test_rtl_minus_normalizer_does_not_break_compact_positive_range():
    assert _ascii('3-12 V') == '3-12 V'


def test_pdf_window_freeze_policy_is_five_pages():
    root = Path(__file__).resolve().parents[1]
    import json
    cfg = json.loads((root/'config'/'phase3_final.json').read_text(encoding='utf-8'))
    assert cfg['pdf_first_pages'] == 5
    assert cfg['pdf_max_calls_per_product'] == 1


def test_v1_2_post_tone_cleanup_never_repairs_density():
    """Final editor output may be measured, but must not be PN-substituted again."""
    pipe = Phase3FinalPipeline.__new__(Phase3FinalPipeline)
    pipe.cfg = {
        'keyword_density_target': {'min': 1.2, 'max': 1.5},
        'deterministic_density_repair_enabled': True,
    }
    body = (
        'TC429CPA یک محصول فروشگاهی است و TC429CPA برای سفارش بررسی می‌شود. '
        'پارت‌نامبر TC429CPA را هنگام ثبت سفارش کنترل کنید. TC429CPA در این متن عمداً تکرار شده است.'
    )
    before_count = body.count('TC429CPA')
    cleaned, repairs = pipe._post_tone_cleanup(body, 'TC429CPA')
    assert cleaned.count('TC429CPA') == before_count
    assert 'این IC' not in cleaned
    assert not any('density' in str(x).lower() for x in repairs)


def test_v1_2_pipeline_version_only_prompts_remain_v1_1_frozen():
    root = Path(__file__).resolve().parents[1]
    import json
    cfg = json.loads((root/'config'/'phase3_final.json').read_text(encoding='utf-8'))
    assert cfg['pipeline_version'] == 'phase3-ALitmate-v1.2'
    assert cfg['agent_version'] == 'phase3-content-agent-altimate-v1.1-frozen'
    assert cfg['prompt_contract_version'] == 'altimate-v1.1-frozen'

