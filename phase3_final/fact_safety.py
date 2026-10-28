import re
from copy import deepcopy


_FA_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬', '01234567890123456789.,')

_UNIT_ALIASES = {
    'v': 'v', 'volt': 'v', 'volts': 'v', 'ولت': 'v',
    'mv': 'mv',
    'a': 'a', 'amp': 'a', 'amps': 'a', 'آمپر': 'a',
    'ma': 'ma', 'ua': 'ua', 'μa': 'ua', 'µa': 'ua',
    'w': 'w', 'mw': 'mw', 'وات': 'w',
    'ω': 'ohm', 'ohm': 'ohm', 'ohms': 'ohm', 'اهم': 'ohm',
    'db': 'db', 'دسیبل': 'db', 'دسی\x1fبل': 'db',
    'hz': 'hz', 'khz': 'khz', 'mhz': 'mhz', 'ghz': 'ghz',
    'ns': 'ns', 'nsec': 'ns', 'nsecs': 'ns', 'nanosecond': 'ns', 'nanoseconds': 'ns',
    'us': 'us', 'usec': 'us', 'usecs': 'us', 'μs': 'us', 'µs': 'us',
    'ms': 'ms', 'msec': 'ms', 'msecs': 'ms',
    'pf': 'pf', 'nf': 'nf', 'uf': 'uf', 'μf': 'uf', 'µf': 'uf',
    '°c': 'c', 'ºc': 'c', 'c': 'c', 'سانتیگراد': 'c',
    '%': '%', '٪': '%',
    'pin': 'pin', 'pins': 'pin', 'پین': 'pin',
    'bit': 'bit', 'bits': 'bit', 'بیت': 'bit',
}

# Unit-bearing numeric claims are the highest-risk hallucination class in this
# storefront. Exact PN digits alone do not match this pattern.
_UNIT_RE = r'(?:mV|mA|uA|µA|μA|mW|kHz|MHz|GHz|Hz|nsec(?:s)?|nanoseconds?|ns|usec(?:s)?|us|µs|μs|msec(?:s)?|ms|pF|nF|uF|µF|μF|°C|ºC|V|A|W|Ω|ohms?|dB|%|٪|pin(?:s)?|bit(?:s)?|ولت|آمپر|وات|اهم|دسی[‌\- ]?بل|سانتیگراد|پین|بیت)'
_SIGNED_NUM = r'[+\-−]?\s*\d+(?:[.,]\d+)?'
_CLAIM_RE = re.compile(r'(?<![\w])(' + _SIGNED_NUM + r')[\s-]*(' + _UNIT_RE + r')(?=$|[^A-Za-z0-9_\u0600-\u06FF])', re.I)
_NUMBER_RE = re.compile(_SIGNED_NUM)
_RANGE_RE = re.compile(r'(?<![\w])(' + _SIGNED_NUM + r')\s*(?:تا|to|bis|through|–|—|\.\.\.|…|-)\s*(' + _SIGNED_NUM + r')[\s-]*(' + _UNIT_RE + r')(?=$|[^A-Za-z0-9_\u0600-\u06FF])', re.I)

_PACKAGE_FAMILY = r'(?:P[ -]?DIP|PDIP|DIP|SOP|SOIC|CERDIP|ZIP|SIP|QFP|TQFP|LQFP)'
_PACKAGE_PIN_FIRST_RE = re.compile(r'\b(\d{1,3})\s*[- ]?\s*(?:pin(?:s)?|پین)\s*[- ]*(' + _PACKAGE_FAMILY + r')\b', re.I)
_PACKAGE_FAMILY_FIRST_RE = re.compile(r'\b(' + _PACKAGE_FAMILY + r')\s*[- ]?\s*(\d{1,3})\b', re.I)
_TO_PACKAGE_RE = re.compile(r'\bTO\s*[- ]?\s*(\d{2,4})(?:[- ]?([A-Za-z0-9]+))?\b')


_NON_CANONICAL_TECH_TERMS = [
    (re.compile(r'سرکوب\s*AM', re.I), 'AM suppression'),
    (re.compile(r'پهنای\s*باند\s*IF', re.I), 'IF bandwidth'),
    (re.compile(r'پهنای\s*باند\s*AF', re.I), 'AF bandwidth'),
    (re.compile(r'خروجی\s*سه[‌\s-]*حالته', re.I), '3-state output'),
]

_INTERNAL_VISIBLE_TERMS = [
    re.compile(r'\bCTA\b', re.I),
    re.compile(r'\bCall\s+to\s+Action\b', re.I),
    re.compile(r'\bValidator\b', re.I),
    re.compile(r'\bPrompt\b', re.I),
    re.compile(r'\bKeyword\s+Density\b', re.I),
    re.compile(r'\bpackage_installation\b', re.I),
    re.compile(r'\bevidence_quote\b', re.I),
    re.compile(r'\bseo_usage\b', re.I),
    re.compile(r'\bfact_status\b', re.I),
    re.compile(r'\bALLOWED_TECHNICAL_FACTS\b', re.I),
    re.compile(r'\bTECHNICAL_TERMS_TO_PRESERVE\b', re.I),
    re.compile(r'\bVALIDATOR_FEEDBACK_ABSOLUTE\b', re.I),
    re.compile(r'\bREQUIRED_INTERNAL_ANCHOR\b', re.I),
]

_WRITER_FACT_FIELDS = (
    'id', 'parameter', 'claim', 'value_text', 'unit', 'condition',
    'section', 'scope', 'seo_usage',
)


def _ascii(value: str) -> str:
    s = (value or '').translate(_FA_DIGITS).replace('−', '-').replace('٬', ',').strip()
    s = re.sub(r'\bمنفی\s*([0-9]+(?:[.,][0-9]+)?)', r'-\1', s)
    # Persian RTL rendering can visually move a leading minus after the number,
    # e.g. ``۰٫۸۸- mA``. Normalize that representation back to ``-0.88 mA``
    # before numeric fact comparison. A compact positive range such as 3-12 V
    # is not changed because the hyphen is followed by another number, not a unit.
    trailing_minus_before_unit = (
        r'(?<![\w.])([0-9]+(?:[.,][0-9]+)?)-'
        r'(?=\s*(?:' + _UNIT_RE + r')(?=$|[^A-Za-z0-9_\u0600-\u06FF]))'
    )
    s = re.sub(trailing_minus_before_unit, r'-\1', s, flags=re.I)
    s = re.sub(r'(?<![\w.])([0-9]+(?:[.,][0-9]+)?)-(?=\s*(?:تا|to|bis|through|–|—|\.\.\.|…))', r'-\1', s, flags=re.I)
    return s


def _canon_num(value: str) -> str:
    value = _ascii(value).replace(' ', '').replace(',', '.')
    try:
        n = float(value)
        if n.is_integer():
            return str(int(n))
        return ('%.12g' % n).rstrip('0').rstrip('.')
    except Exception:
        return value.casefold()


def _canon_unit(raw: str) -> str:
    u = _ascii(raw).strip().casefold().replace('\u200c', '').replace('-', '').replace(' ', '')
    if u in {'دسیبل', 'دسی\x1fبل'}:
        return 'db'
    return _UNIT_ALIASES.get(u, u)


def _extract_mentions(text: str):
    src = _ascii(text)
    out = []
    occupied = []
    # In a range such as -40 to 85°C, the unit semantically applies to both
    # endpoints. Audit both numbers rather than only the endpoint carrying it.
    for m in _RANGE_RE.finditer(src):
        unit = _canon_unit(m.group(3))
        out.append({'text': m.group(0), 'number': _canon_num(m.group(1)), 'unit': unit, 'start': m.start(), 'range_endpoint': 'start'})
        out.append({'text': m.group(0), 'number': _canon_num(m.group(2)), 'unit': unit, 'start': m.start(), 'range_endpoint': 'end'})
        occupied.append((m.start(), m.end()))
    for m in _CLAIM_RE.finditer(src):
        if any(a <= m.start() < b for a, b in occupied):
            continue
        full = m.group(0)
        num = _canon_num(m.group(1))
        unit_raw = m.group(2)
        unit = _canon_unit(unit_raw)
        out.append({'text': full, 'number': num, 'unit': unit, 'start': m.start()})
    return out


def _canon_package_family(raw: str) -> str:
    f = re.sub(r'[\s-]+', '', _ascii(raw).upper())
    if f == 'PDIP':
        return 'PDIP'
    return f


def _extract_packages(text: str):
    src = _ascii(text)
    out = []
    occupied = []
    for rx, pin_first in ((_PACKAGE_PIN_FIRST_RE, True), (_PACKAGE_FAMILY_FIRST_RE, False)):
        for m in rx.finditer(src):
            if any(a <= m.start() < b for a, b in occupied):
                continue
            pins = m.group(1) if pin_first else m.group(2)
            family = m.group(2) if pin_first else m.group(1)
            key = f'{_canon_package_family(family)}:{int(pins)}'
            out.append({'text': m.group(0), 'family': _canon_package_family(family), 'pins': int(pins), 'key': key})
            occupied.append((m.start(), m.end()))
    for m in _TO_PACKAGE_RE.finditer(src):
        if any(a <= m.start() < b for a, b in occupied):
            continue
        suffix = (m.group(2) or '').upper()
        key = f'TO:{int(m.group(1))}:{suffix}'
        out.append({'text': m.group(0), 'family': 'TO', 'pins': None, 'key': key})
    return out


def _package_claim_supported(claim_key: str, allowed_keys) -> bool:
    """Return True when a package claim is no more specific than verified evidence.

    Exact matches always pass. For TO packages, a generic family claim such as
    ``TO:92:`` is allowed when the verified evidence is a more specific member of
    the same family, e.g. ``TO:92:3L``. The reverse is deliberately forbidden:
    verified ``TO:92:`` does not authorize a new ``TO:92:3L`` detail.
    """
    allowed = set(allowed_keys or ())
    if claim_key in allowed:
        return True
    m = re.fullmatch(r'TO:(\d+):([^:]*)', str(claim_key or ''))
    if not m:
        return False
    number, suffix = m.group(1), m.group(2)
    if suffix:
        return False
    prefix = f'TO:{number}:'
    return any(str(k).startswith(prefix) for k in allowed)


def _project_fact(fact: dict) -> dict:
    # V4.1 boundary: evidence_quote is an audit artifact, not writer knowledge.
    # In particular, a target fact may have an evidence block that also lists
    # sibling variants. Exposing it would widen the allowed numeric universe.
    return {k: deepcopy(fact.get(k)) for k in _WRITER_FACT_FIELDS if k in fact}


def project_safe_facts(facts_obj: dict | None) -> dict | None:
    """Return only writer-authorized facts; never expose audit/rejected/evidence data."""
    if not facts_obj:
        return None
    normal = [_project_fact(x) for x in facts_obj.get('seo_ready_facts', [])]
    limits = [_project_fact(x) for x in facts_obj.get('limit_only_facts', [])]
    return {
        'schema_version': 'phase3-writer-safe-facts-v5.0',
        'part_number': facts_obj.get('part_number'),
        'seo_ready_facts': normal,
        'limit_only_facts': limits,
    }


def canonical_terms_to_preserve(safe_facts: dict | None):
    if not safe_facts:
        return []
    terms = []
    seen = set()
    for fact in safe_facts.get('seo_ready_facts', []) + safe_facts.get('limit_only_facts', []):
        p = (fact.get('parameter') or '').strip()
        # Preserve terms that visibly carry standard Latin technical notation.
        if p and re.search(r'[A-Za-z]', p):
            key = p.casefold()
            if key not in seen:
                seen.add(key)
                terms.append(p)
    return terms


def _bare_numbers(value_text: str):
    text = _ascii(value_text)
    # Distinguish an ordinary hyphen range (3 - 12) from a negative sign.
    text = re.sub(r'(?<=\d)\s+-\s+(?=\d)', ' to ', text)
    return [_canon_num(x) for x in _NUMBER_RE.findall(text)]


def _allowed_numeric_pairs(safe_facts: dict | None):
    allowed = set()
    if not safe_facts:
        return allowed
    for fact in safe_facts.get('seo_ready_facts', []) + safe_facts.get('limit_only_facts', []):
        unit = fact.get('unit')
        value_text = _ascii(fact.get('value_text') or '')
        if unit:
            cu = _canon_unit(str(unit))
            for n in _bare_numbers(value_text):
                allowed.add((n, cu))
        # Only approved canonical fact fields may authorize customer-visible
        # numeric claims. evidence_quote is deliberately excluded in V4.1.
        corpus = ' '.join(str(fact.get(k) or '') for k in ('parameter', 'claim', 'value_text', 'condition'))
        corpus = re.sub(r'\\text\s*\{([^}]*)\}', r'\1', corpus)
        corpus = corpus.replace('\\dots', ' to ').replace('\\ldots', ' to ')
        for mention in _extract_mentions(corpus):
            allowed.add((mention['number'], mention['unit']))
    return allowed


def _allowed_packages(safe_facts: dict | None):
    allowed = set()
    if not safe_facts:
        return allowed
    for fact in safe_facts.get('seo_ready_facts', []) + safe_facts.get('limit_only_facts', []):
        corpus = ' '.join(str(fact.get(k) or '') for k in ('parameter', 'claim', 'value_text', 'condition'))
        corpus = re.sub(r'\\text\s*\{([^}]*)\}', r'\1', corpus)
        corpus = corpus.replace('\\dots', ' to ').replace('\\ldots', ' to ')
        allowed.update(x['key'] for x in _extract_packages(corpus))
    return allowed


def validate_fact_safety(md: str, safe_facts: dict | None, content_mode: str, verified_identity: dict | None = None):
    allowed = _allowed_numeric_pairs(safe_facts)
    allowed_packages = _allowed_packages(safe_facts)
    verified_identity = verified_identity or {}
    verified_pkg = str(verified_identity.get('verified_package_installation') or '')
    allowed_packages.update(x['key'] for x in _extract_packages(verified_pkg))
    for x in _extract_mentions(verified_pkg):
        allowed.add((x['number'], x['unit']))
    mentions = _extract_mentions(md)
    packages = _extract_packages(md)
    unsupported = []
    for x in mentions:
        pair = (x['number'], x['unit'])
        if pair not in allowed:
            unsupported.append({
                'code': 'UNSUPPORTED_TECHNICAL_CLAIM',
                'claim': x['text'],
                'number': x['number'],
                'unit': x['unit'],
            })
    for pkg in packages:
        if not _package_claim_supported(pkg['key'], allowed_packages):
            unsupported.append({
                'code': 'UNSUPPORTED_PACKAGE_CLAIM',
                'claim': pkg['text'],
                'package': pkg['text'],
                'canonical_package': pkg['key'],
            })

    # Commercial-only has no datasheet facts, but independently verified
    # identity (for example a verified package) may still be used. Everything
    # else remains forbidden.
    if content_mode != 'TECHNICAL_LIGHT':
        unsupported = [{
            'code': 'COMMERCIAL_ONLY_TECHNICAL_CLAIM',
            'claim': x['text'],
            'number': x['number'],
            'unit': x['unit'],
        } for x in mentions if (x['number'], x['unit']) not in allowed] + [{
            'code': 'COMMERCIAL_ONLY_PACKAGE_CLAIM',
            'claim': pkg['text'],
            'package': pkg['text'],
            'canonical_package': pkg['key'],
        } for pkg in packages if not _package_claim_supported(pkg['key'], allowed_packages)]

    visible_internal = []
    for rx in _INTERNAL_VISIBLE_TERMS:
        for m in rx.finditer(md):
            visible_internal.append({
                'code': 'INTERNAL_INSTRUCTION_LEAK',
                'term': m.group(0),
            })

    terminology = []
    seen_terms = set()
    for rx, canonical in _NON_CANONICAL_TECH_TERMS:
        for m in rx.finditer(md):
            key = (m.group(0).casefold(), canonical.casefold())
            if key in seen_terms:
                continue
            seen_terms.add(key)
            terminology.append({
                'code': 'NON_CANONICAL_TECHNICAL_TERM',
                'term': m.group(0),
                'use_instead': canonical,
            })

    failures = unsupported + visible_internal + terminology
    return {
        'passed': not failures,
        'failures': failures,
        'unsupported_claims': unsupported,
        'internal_instruction_leaks': visible_internal,
        'terminology_failures': terminology,
        'measured': {
            'technical_numeric_mentions': len(mentions),
            'allowed_numeric_pairs': len(allowed),
            'package_mentions': len(packages),
            'allowed_packages': len(allowed_packages),
        },
    }
