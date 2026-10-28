from phase3_fact_extraction.coverage import classify_priority_fact, build_coverage

CFG={
    'fact_coverage':{
        'minimum_useful_facts':5,
        'minimum_priority_categories':3,
        'alternative_useful_facts':8,
    }
}

def f(parameter, section='ELECTRICAL_CHARACTERISTIC', unit=None, seo_usage='NORMAL'):
    return {'parameter':parameter,'section':section,'unit':unit,'seo_usage':seo_usage,'claim':parameter,'value_text':'x','condition':None}


def test_priority_classifier_covers_requested_categories():
    assert 'voltage' in classify_priority_fact(f('Operating supply voltage','OPERATING_CONDITION','V'))
    assert 'current' in classify_priority_fact(f('Supply current','ELECTRICAL_CHARACTERISTIC','mA'))
    assert 'package' in classify_priority_fact(f('Package','PACKAGE'))
    assert 'application_or_function' in classify_priority_fact(f('Function','FUNCTION'))
    assert 'frequency' in classify_priority_fact(f('Switching frequency','ELECTRICAL_CHARACTERISTIC','MHz'))
    assert 'operating_temperature' in classify_priority_fact(f('Operating ambient temperature','OPERATING_CONDITION','°C'))


def test_priorities_are_not_whitelist_and_other_facts_count():
    facts={'seo_ready_facts':[
        f('Operating supply voltage'), f('Supply current'), f('Package','PACKAGE'),
        f('Propagation delay'), f('Logic high threshold'),
    ]}
    c=build_coverage(facts,CFG,exact_part_number_covered=True)
    assert c['useful_fact_count']==5
    assert c['priority_count']>=3
    assert c['sufficient'] is True


def test_eight_useful_facts_can_pass_without_three_priorities():
    facts={'seo_ready_facts':[f(f'Other useful fact {i}') for i in range(8)]}
    c=build_coverage(facts,CFG,exact_part_number_covered=True)
    assert c['priority_count']==0
    assert c['sufficient'] is True


def test_identity_failure_always_requires_fallback():
    facts={'seo_ready_facts':[f(f'Other useful fact {i}') for i in range(10)]}
    c=build_coverage(facts,CFG,exact_part_number_covered=False)
    assert c['sufficient'] is False
    assert c['reason']=='EXACT_PART_NUMBER_NOT_CONFIRMED'

def test_limit_only_rated_facts_count_for_coverage_but_remain_limit_only():
    facts={
        'seo_ready_facts':[f('Package','PACKAGE'), f('Function','FUNCTION'), f('Switching frequency','ELECTRICAL_CHARACTERISTIC','MHz')],
        'limit_only_facts':[
            f('Collector-emitter voltage','ABSOLUTE_MAXIMUM','V',seo_usage='LIMIT_ONLY'),
            f('Collector current','ABSOLUTE_MAXIMUM','A',seo_usage='LIMIT_ONLY'),
        ],
    }
    c=build_coverage(facts,CFG,exact_part_number_covered=True)
    assert c['useful_fact_count']==5
    assert c['priority_found']['voltage'] is True
    assert c['priority_found']['current'] is True
    assert c['sufficient'] is True
