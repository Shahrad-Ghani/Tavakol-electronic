_WRITER_ACTIONABLE_SEO = {
    'keyword_in_title',
    'keyword_in_meta_description',
    'keyword_in_first_10_percent',
    'keyword_in_content',
    'keyword_in_subheadings',
    'keyword_density',
    'keyword_in_image_alt',
    'short_paragraphs',
    'title_start_with_keyword',
}

_NON_WRITER_STRUCTURE = {
    'internal_policy_link_exact',
    'internal_policy_link_in_body',
}


def build_validator_feedback(
    analysis: dict,
    structure: dict,
    link_selection: dict,
    fact_safety: dict | None = None,
    hard_gates: dict | None = None,
):
    s = analysis['_scoring']
    actionable = []
    non_actionable = []
    warnings = set(structure.get('warnings', []))

    if hard_gates:
        for gate_name, gate in hard_gates.items():
            if gate.get('status') == 'FAIL':
                actionable.append({
                    'type': 'HARD_GATE',
                    'test': gate_name,
                    'required': True,
                    'evidence': gate.get('evidence', []),
                    'action': 'RESTORE_EXACT_TARGET_PART_NUMBER',
                })

    for test, maxv in s['max_scores'].items():
        got = s['earned'].get(test, 0)
        if got >= maxv:
            continue
        finding = {'type': 'SEO', 'test': test, 'earned': got, 'max': maxv}
        # V4.1: a non-severe density warning must not indirectly buy a retry
        # merely because the frozen RankMath-like scorer awards fewer points.
        if test == 'keyword_density' and 'keyword_density_non_severe' in warnings:
            finding['reason'] = 'NON_SEVERE_WARNING_ONLY_V4_1'
            non_actionable.append(finding)
        elif test in _WRITER_ACTIONABLE_SEO:
            actionable.append(finding)
        else:
            non_actionable.append(finding)

    for code in structure.get('failures', []):
        finding = {'type': 'STRUCTURE', 'test': code, 'required': True}
        if code in _NON_WRITER_STRUCTURE:
            non_actionable.append(finding)
        else:
            if code == 'word_count_not_severely_outside_target':
                finding['measured'] = {
                    'current': structure.get('measured', {}).get('word_count'),
                    'target': structure.get('measured', {}).get('word_count_target'),
                    'distance': structure.get('measured', {}).get('word_count_distance_from_target'),
                    'soft_tolerance': structure.get('measured', {}).get('word_count_soft_tolerance_words'),
                }
            if code == 'keyword_density_not_severely_outside_target':
                finding['measured'] = {
                    'current': structure.get('measured', {}).get('keyword_density'),
                    'target': structure.get('measured', {}).get('keyword_density_target'),
                    'acceptable_range': structure.get('measured', {}).get('keyword_density_acceptable_range'),
                    'distance': structure.get('measured', {}).get('keyword_density_distance_from_target'),
                }
            actionable.append(finding)

    if fact_safety and not fact_safety.get('passed', True):
        for item in fact_safety.get('failures', []):
            actionable.append({
                'type': 'FACT_SAFETY',
                'test': item.get('code'),
                'required': True,
                'evidence': item,
                'action': 'REMOVE_OR_REWRITE_UNSUPPORTED_CLAIM',
            })

    return {
        'ABSOLUTE': True,
        'instruction': (
            'Fix every item in failures. Preserve verified identity and ONLY the supplied '
            'allowed technical facts. Remove any unsupported technical claim. Do not chase '
            'non_actionable_findings in the writing attempt. Non-severe numeric warnings '
            '(including word count and keyword density) are not failures and must not trigger rewriting.'
        ),
        'seo_score': analysis['score'],
        'failures': actionable,
        'non_actionable_findings': non_actionable,
        'warnings': structure.get('warnings', []),
        'actionable_retry_needed': bool(actionable),
        'required_internal_anchor': link_selection['anchor'],
        'internal_link_url_owned_by_postprocessor': True,
        'forbidden': [
            'invent technical facts',
            'use rejected/audit facts',
            'change exact part number',
            'invent URL',
            'replace target with near variant',
            'show internal instruction terms such as CTA, Validator, Prompt or package_installation',
            'translate canonical technical terms supplied in TECHNICAL_TERMS_TO_PRESERVE',
        ],
    }
