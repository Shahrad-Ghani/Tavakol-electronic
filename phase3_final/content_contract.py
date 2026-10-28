import re
from phase3b_validator.markdown_tools import headings, markdown_links, paragraphs
from phase3b_validator.normalization import lower, normalize_text


def _contains(text, needle):
    return lower(needle) in lower(text or '')


def _fa_semantic_lower(value: str) -> str:
    value = normalize_text(value).casefold()
    return value.translate(str.maketrans({
        'ؤ': 'و',
        'ي': 'ی',
        'ى': 'ی',
        'ك': 'ک',
    }))


def _table_present(md):
    lines = md.splitlines()
    for i in range(len(lines) - 1):
        if lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
            sep = lines[i + 1].strip()
            if sep.startswith('|') and re.search(r'---+', sep):
                return True
    return False


def _bold_heading_lines(md, levels=(2, 3)):
    matches = []
    for line in md.splitlines():
        m = re.match(r'^\s*(#{1,6})\s+(.+?)\s*$', line)
        if not m:
            continue
        level = len(m.group(1))
        txt = m.group(2).strip()
        if level in levels:
            matches.append(bool(re.match(r'^\*\*.+\*\*$', txt)))
    return matches


def _mode_word_policy(content_mode: str, cfg: dict):
    if content_mode == 'TECHNICAL_LIGHT':
        return cfg['technical_target_words']
    return cfg['commercial_target_words']


def _distance_from_range(value: float, low: float, high: float) -> float:
    if value < low:
        return low - value
    if value > high:
        return value - high
    return 0.0


def _soft_range_status(value: float, low: float, high: float, tolerance: float):
    distance = _distance_from_range(value, low, high)
    if distance == 0:
        return 'PASS', distance
    if distance <= tolerance:
        return 'WARNING_NON_SEVERE', distance
    return 'FAIL_SEVERE', distance



def _h2_sections(md: str):
    """Return [(heading_text, lines_after_heading_until_next_h2), ...]."""
    out = []
    current = None
    for line in (md or '').splitlines():
        m = re.match(r'^\s*##\s+(.+?)\s*$', line)
        if m:
            if current is not None:
                out.append(current)
            current = [normalize_text(m.group(1)), []]
        elif current is not None:
            current[1].append(line)
    if current is not None:
        out.append(current)
    return out


def _has_real_section_content(lines):
    for line in lines:
        st = line.strip()
        if not st or st in {'---', '***', '___'}:
            continue
        if re.match(r'^#{1,6}\s+', st):
            continue
        # A table row or prose paragraph counts as real section content.
        if st:
            return True
    return False


def _faq_answer_status(md: str):
    """Return (question_count, answered_question_count) inside FAQ H2 sections."""
    question_count = answered = 0
    in_faq = False
    current_answer_has_content = False
    current_question = False
    for line in (md or '').splitlines():
        h2 = re.match(r'^\s*##\s+(.+?)\s*$', line)
        if h2:
            if current_question:
                answered += int(current_answer_has_content)
            current_question = False
            current_answer_has_content = False
            title = _fa_semantic_lower(h2.group(1))
            in_faq = ('سوالات متداول' in title) or ('سؤالات متداول' in title) or ('پرسش' in title) or ('faq' in title)
            continue
        if not in_faq:
            continue
        h3 = re.match(r'^\s*###\s+(.+?)\s*$', line)
        if h3:
            if current_question:
                answered += int(current_answer_has_content)
            current_question = True
            current_answer_has_content = False
            question_count += 1
            continue
        st = line.strip()
        if current_question and st and st not in {'---', '***', '___'} and not re.match(r'^#{1,6}\s+', st):
            current_answer_has_content = True
    if current_question:
        answered += int(current_answer_has_content)
    return question_count, answered

def validate_content_contract(
    bundle: dict,
    md: str,
    part_number: str,
    link_selection: dict,
    *,
    seo_metrics: dict | None = None,
    policy_cfg: dict | None = None,
):
    hs = headings(md)
    h1 = [t for lvl, t in hs if lvl == 1]
    h2 = [t for lvl, t in hs if lvl == 2]
    h3 = [t for lvl, t in hs if lvl == 3]

    page_h1 = bundle.get('page', {}).get('product_title', '')
    faq_h2 = any(
        ('سوالات متداول' in _fa_semantic_lower(t))
        or ('پرسش' in _fa_semantic_lower(t))
        or ('faq' in _fa_semantic_lower(t))
        for t in h2
    )
    purchase_h2 = any(('قیمت' in t) or ('استعلام' in t) or ('موجودی' in t) or t.strip('* ').startswith('خرید') for t in h2)
    cta_h2 = any(('جمع' in t) or ('سفارش' in t) or ('نتیجه' in t) for t in h2)
    seps = sum(1 for ln in md.splitlines() if ln.strip() == '---')
    ps = paragraphs(md)
    links = markdown_links(md)
    policy_links = [
        x for x in links
        if x.get('url') == link_selection['target_url']
        and x.get('text') == link_selection['anchor']
    ]
    # Altimate V1: count the policy anchor only when it is actually a link. Bare text
    # in headings (e.g. 'قیمت آی سی') must not create a false duplicate.
    selected_link_occurrences = sum(1 for x in links if lower(x.get('text','')) == lower(link_selection['anchor']))
    policy_link_in_body = False
    exact_md = f"[{link_selection['anchor']}]({link_selection['target_url']})"
    for line in md.splitlines():
        if exact_md in line and not line.lstrip().startswith(('#', '|')):
            policy_link_in_body = True
            break
    bold_flags = _bold_heading_lines(md)
    h2_sections = _h2_sections(md)
    purchase_sections = [lines for title, lines in h2_sections if (('قیمت' in title) or ('استعلام' in title) or ('موجودی' in title) or title.strip('* ').startswith('خرید'))]
    cta_sections = [lines for title, lines in h2_sections if ('جمع' in title or 'سفارش' in title or 'نتیجه' in title)]
    faq_questions, faq_answered = _faq_answer_status(md)
    all_h2_nonempty = bool(h2_sections) and all(_has_real_section_content(lines) for _title, lines in h2_sections)

    checks = {
        'page_h1_present': bool(page_h1.strip()),
        'page_h1_has_exact_pn': _contains(page_h1, part_number),
        'no_duplicate_body_h1': len(h1) == 0,
        'h2_present': len(h2) >= 3,
        'h3_present': len(h3) >= 2,
        'pn_in_h2': any(_contains(t, part_number) for t in h2),
        'pn_in_h3': any(_contains(t, part_number) for t in h3),
        'headings_bold': bool(bold_flags) and all(bold_flags),
        'table_present': _table_present(md),
        'faq_present': faq_h2 and faq_questions >= 2,
        'faq_answers_nonempty': faq_questions >= 2 and faq_answered >= 2,
        'section_separators': seps >= max(2, len(h2) - 1),
        'explanatory_paragraphs': len(ps) >= 4,
        'purchase_price_section': purchase_h2,
        'purchase_price_section_nonempty': bool(purchase_sections) and any(_has_real_section_content(x) for x in purchase_sections),
        'cta_section': cta_h2,
        'cta_section_nonempty': bool(cta_sections) and any(_has_real_section_content(x) for x in cta_sections),
        'all_h2_sections_nonempty': all_h2_nonempty,
        'internal_policy_link_exact': len(policy_links) == 1,
        'internal_policy_anchor_once': selected_link_occurrences == 1,
        'internal_policy_link_in_body': policy_link_in_body,
    }

    measured = {
        'body_h1_count': len(h1),
        'h2_count': len(h2),
        'h3_count': len(h3),
        'separator_count': seps,
        'paragraph_count': len(ps),
        'selected_anchor_occurrences': selected_link_occurrences,
        'faq_question_count': faq_questions,
        'faq_answered_count': faq_answered,
        'policy_link_count': len(policy_links),
    }
    warnings = []

    if seo_metrics is not None and policy_cfg is not None:
        density = float(seo_metrics.get('keyword_density', 0.0))
        word_count = int(seo_metrics.get('word_count', 0))
        dpol = policy_cfg['keyword_density_target']
        content_mode = bundle.get('identity', {}).get('content_mode', '')
        wpol = _mode_word_policy(content_mode, policy_cfg)
        word_tolerance = int(policy_cfg.get('word_count_soft_tolerance_words', 120))
        density_tolerance = float(policy_cfg.get('keyword_density_soft_tolerance', 0.2))
        word_status, word_distance = _soft_range_status(
            word_count, float(wpol['min']), float(wpol['max']), float(word_tolerance)
        )
        density_status, density_distance = _soft_range_status(
            density, float(dpol['min']), float(dpol['max']), density_tolerance
        )

        # Frozen V4.1 policy: numeric targets are ideals, not perfection gates.
        # Small deviations are warning-only and MUST NOT trigger regeneration.
        checks['keyword_density_not_severely_outside_target'] = density_status != 'FAIL_SEVERE'
        checks['word_count_not_severely_outside_target'] = word_status != 'FAIL_SEVERE'
        if density_status == 'WARNING_NON_SEVERE':
            warnings.append('keyword_density_non_severe')
        if word_status == 'WARNING_NON_SEVERE':
            warnings.append('word_count_non_severe')

        measured.update({
            'keyword_density': density,
            'keyword_density_target': {'min': dpol['min'], 'max': dpol['max']},
            'keyword_density_soft_tolerance': density_tolerance,
            'keyword_density_acceptable_range': {
                'min': round(float(dpol['min']) - density_tolerance, 4),
                'max': round(float(dpol['max']) + density_tolerance, 4),
            },
            'keyword_density_distance_from_target': round(density_distance, 4),
            'keyword_density_status': density_status,
            'word_count': word_count,
            'word_count_target': {'min': wpol['min'], 'max': wpol['max']},
            'word_count_distance_from_target': int(word_distance),
            'word_count_soft_tolerance_words': word_tolerance,
            'word_count_status': word_status,
        })

    failures = [k for k, v in checks.items() if not v]
    return {
        'passed': not failures,
        'checks': checks,
        'failures': failures,
        'warnings': warnings,
        'measured': measured,
    }
