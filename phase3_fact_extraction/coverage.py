import re

PRIORITY_KEYS = (
    'voltage',
    'current',
    'package',
    'application_or_function',
    'frequency',
    'operating_temperature',
)


def _text(fact):
    return ' '.join(str(fact.get(k) or '') for k in ('parameter','claim','value_text','unit','condition','section')).casefold()


def classify_priority_fact(fact):
    """Map an extracted fact to user-priority coverage categories.

    This is a fallback-routing heuristic, never an extraction whitelist. Rated
    voltage/current can legitimately be LIMIT_ONLY in semiconductor datasheets,
    so they may count for coverage while still remaining LIMIT_ONLY for writing.
    """
    if fact.get('seo_usage') == 'NEVER':
        return set()
    t = _text(fact)
    section = str(fact.get('section') or '')
    out = set()

    if re.search(r'\bvoltage\b|\bvoltage rating\b|\bvce\b|\bvds\b|ولتاژ', t):
        out.add('voltage')
    if re.search(r'\bcurrent\b|\bcurrent rating\b|\bic\b|\bid\b|جریان', t):
        out.add('current')
    if section == 'PACKAGE' or re.search(r'\bpackage\b|\bpdip\b|\bdip\b|\bcerdip\b|\bsoic\b|\bqfp\b|\bto[- ]?\d+\b|پکیج', t):
        out.add('package')
    if section in {'APPLICATION','FUNCTION'} or re.search(r'\bapplication\b|\bfunction\b|\bused for\b|کاربرد|عملکرد|کارکرد', t):
        out.add('application_or_function')
    if re.search(r'\bfrequency\b|\bclock\b|\bswitching frequency\b|\bbandwidth\b|\b(?:khz|mhz|ghz|hz)\b|فرکانس|پهنای باند', t):
        out.add('frequency')
    if re.search(r'\boperating.*temperature\b|\bambient temperature\b|دمای کاری|دمای محیط', t):
        if 'storage' not in t:
            out.add('operating_temperature')
    return out


def build_coverage(facts_obj, cfg, *, exact_part_number_covered=True):
    normal = list((facts_obj or {}).get('seo_ready_facts') or [])
    limits = list((facts_obj or {}).get('limit_only_facts') or [])
    useful_facts = normal + limits
    found = {k: False for k in PRIORITY_KEYS}
    for fact in useful_facts:
        for key in classify_priority_fact(fact):
            found[key] = True

    useful = len(useful_facts)
    priority_count = sum(1 for v in found.values() if v)
    pol = cfg.get('fact_coverage') or {}
    min_useful = int(pol.get('minimum_useful_facts', 5))
    min_priority = int(pol.get('minimum_priority_categories', 3))
    alt_useful = int(pol.get('alternative_useful_facts', 8))

    sufficient = bool(exact_part_number_covered) and (
        (useful >= min_useful and priority_count >= min_priority)
        or useful >= alt_useful
    )
    missing = [k for k, v in found.items() if not v]
    if not exact_part_number_covered:
        reason = 'EXACT_PART_NUMBER_NOT_CONFIRMED'
    elif sufficient:
        reason = 'COVERAGE_SUFFICIENT'
    else:
        reason = 'COVERAGE_BELOW_FALLBACK_THRESHOLD'
    return {
        'sufficient': sufficient,
        'reason': reason,
        'useful_fact_count': useful,
        'normal_fact_count': len(normal),
        'limit_only_fact_count': len(limits),
        'priority_found': found,
        'priority_count': priority_count,
        'priority_total': len(found),
        'priority_coverage_pct': round(priority_count / max(1, len(found)) * 100.0, 2),
        'missing_priority_categories': missing,
        'policy': {
            'minimum_useful_facts': min_useful,
            'minimum_priority_categories': min_priority,
            'alternative_useful_facts': alt_useful,
        },
    }
