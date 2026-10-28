def _tone_diag(tone_record):
    result = (tone_record or {}).get('result') or {}
    return {
        'status': (tone_record or {}).get('status'),
        'naturalness_score': result.get('naturalness_score'),
        'ai_like_style_score_diagnostic': result.get('ai_like_style_score'),
        'flags': result.get('flags') or [],
    }


def build_product_scorecard(*, product, candidate, tone_record, final_audit, cost_accounting, writer_expensive_used):
    source = product.get('source', {})
    coverage = source.get('priority_fact_coverage') or {}
    structure = candidate.get('structure') or {}
    editorial_metric_failures = {'keyword_density_not_severely_outside_target', 'word_count_not_severely_outside_target'}
    structure_failures = set(structure.get('failures') or [])
    core_structure_pass = not (structure_failures - editorial_metric_failures)
    metrics = (candidate.get('analysis') or {}).get('_metrics') or {}
    fact_safety = candidate.get('fact_safety') or {}
    audit = final_audit or {}
    return {
        'quality_metric_policy': 'PASS_RATE_IS_OPERATIONAL_ONLY_NOT_PRIMARY_QUALITY_METRIC',
        'fact_extraction': {
            'useful_fact_count': int(source.get('useful_fact_count') or 0),
            'priority_count': int(coverage.get('priority_count') or 0),
            'priority_total': int(coverage.get('priority_total') or 6),
            'priority_coverage_pct': float(coverage.get('priority_coverage_pct') or 0.0),
            'coverage_sufficient': bool(coverage.get('sufficient')),
            'missing_priority_categories': coverage.get('missing_priority_categories') or [],
            'pdf_calls': int(source.get('pdf_calls') or 0),
            'pdf_fallback_used': bool(source.get('pdf_fallback_used')),
        },
        'content_factuality': {
            'hard_gate_pass': bool(candidate.get('hard_gate_pass')),
            'local_fact_safety_pass': bool(candidate.get('fact_safety_pass')),
            'local_fact_safety_failures': fact_safety.get('failures') or [],
            'facts_only_audit_status': audit.get('status'),
            'wrong_values': audit.get('wrong_values') or [],
            'wrong_units': audit.get('wrong_units') or [],
            'wrong_conditions': audit.get('wrong_conditions') or [],
            'variant_leakage': audit.get('variant_leakage') or [],
            'unsupported_technical_claims': audit.get('unsupported_technical_claims') or [],
        },
        'content_usefulness': {
            'structure_pass': bool(core_structure_pass),
            'full_contract_pass_including_editorial_metrics': bool(candidate.get('contract_pass')),
            'table_present': bool((structure.get('checks') or {}).get('table_present')),
            'purchase_section_present': bool((structure.get('checks') or {}).get('purchase_price_section')),
            'faq_present': bool((structure.get('checks') or {}).get('faq_present')),
            'cta_present': bool((structure.get('checks') or {}).get('cta_section')),
        },
        'tone': _tone_diag(tone_record),
        'seo': {
            'score': int(candidate.get('score') or 0),
            'publish_gate': False,
            'policy': 'SEO_SCORE_IS_QUALITY_METRIC_NOT_PUBLICATION_GATE',
            'keyword_density': metrics.get('keyword_density'),
            'word_count': metrics.get('word_count'),
            'structure_pass': bool(core_structure_pass),
            'full_contract_pass_including_editorial_metrics': bool(candidate.get('contract_pass')),
        },
        'cost_and_escalation': {
            'estimated_total_cost_usd': float((cost_accounting or {}).get('estimated_total_cost_usd') or 0.0),
            'pdf_calls': int(source.get('pdf_calls') or 0),
            'pdf_fallback_used': bool(source.get('pdf_fallback_used')),
            'expensive_writer_used': bool(writer_expensive_used),
        },
    }


def aggregate_batch_scorecard(items):
    total = len(items)
    if not total:
        return {
            'quality_metric_policy':'PASS_RATE_IS_OPERATIONAL_ONLY_NOT_PRIMARY_QUALITY_METRIC',
            'products':0,
        }
    cards = [x.get('scorecard') or {} for x in items]
    fact_cards = [c.get('fact_extraction') or {} for c in cards]
    seo_cards = [c.get('seo') or {} for c in cards]
    cost_cards = [c.get('cost_and_escalation') or {} for c in cards]
    technical = [c for c in fact_cards if int(c.get('pdf_calls') or 0) > 0]
    pass_count = sum(1 for x in items if x.get('status') == 'PASS')
    return {
        'quality_metric_policy':'PASS_RATE_IS_OPERATIONAL_ONLY_NOT_PRIMARY_QUALITY_METRIC',
        'products':total,
        'operational_pass_rate_pct':round(pass_count/total*100.0,2),
        'average_seo_score':round(sum(float(c.get('score') or 0) for c in seo_cards)/total,2),
        'average_estimated_cost_usd':round(sum(float(c.get('estimated_total_cost_usd') or 0) for c in cost_cards)/total,8),
        'technical_products':len(technical),
        'average_pdf_calls_per_technical_product':round(sum(int(c.get('pdf_calls') or 0) for c in technical)/max(1,len(technical)),3),
        'pdf_fallback_rate_pct':round(sum(1 for c in technical if c.get('pdf_fallback_used'))/max(1,len(technical))*100.0,2),
        'expensive_writer_rate_pct':round(sum(1 for c in cost_cards if c.get('expensive_writer_used'))/total*100.0,2),
        'average_priority_fact_coverage_pct':round(sum(float(c.get('priority_coverage_pct') or 0) for c in technical)/max(1,len(technical)),2),
    }
