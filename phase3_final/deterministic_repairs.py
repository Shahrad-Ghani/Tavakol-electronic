import re


def _heading_text(line: str):
    m = re.match(r'^(#{1,6})\s+(.+?)\s*$', line.strip())
    if not m:
        return None
    raw = m.group(2).strip()
    if raw.startswith('**') and raw.endswith('**') and len(raw) >= 4:
        raw = raw[2:-2].strip()
    return len(m.group(1)), raw


def _normalize_headings(md: str) -> str:
    out = []
    for line in (md or '').splitlines():
        h = _heading_text(line)
        if not h:
            out.append(line)
            continue
        level, text = h
        # WooCommerce product title owns H1. Body H1 becomes H2.
        if level == 1:
            level = 2
        if level in (2, 3):
            line = '#' * level + f' **{text}**'
        out.append(line)
    return '\n'.join(out).strip()


def _heading_sets(md: str):
    h2, h3 = [], []
    for line in md.splitlines():
        h = _heading_text(line)
        if not h:
            continue
        lvl, text = h
        if lvl == 2:
            h2.append(text)
        elif lvl == 3:
            h3.append(text)
    return h2, h3


def _has_table(md: str) -> bool:
    lines = md.splitlines()
    for i in range(len(lines) - 1):
        if lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
            if re.match(r'^\s*\|?\s*:?-{3,}', lines[i + 1]):
                return True
    return False


def _append_section(md: str, section: str) -> str:
    md = md.rstrip()
    if md and not md.endswith('---'):
        md += '\n\n---'
    return md + '\n\n' + section.strip() + '\n'


def _ensure_separators(md: str) -> str:
    lines = md.splitlines()
    out = []
    seen_h2 = False
    for line in lines:
        h = _heading_text(line)
        if h and h[0] == 2:
            if seen_h2:
                j = len(out) - 1
                while j >= 0 and not out[j].strip():
                    j -= 1
                if j < 0 or out[j].strip() != '---':
                    out.extend(['', '---', ''])
            seen_h2 = True
        out.append(line)
    return '\n'.join(out).strip()



def _fa_heading_normalize(text: str) -> str:
    t = (text or '').casefold().replace('ي', 'ی').replace('ك', 'ک').replace('ؤ', 'و')
    t = t.replace('\u200c', ' ')
    t = re.sub(r'[*_`]+', '', t)
    return re.sub(r'\s+', ' ', t).strip()


def intro_heading_status(md: str, part_number: str, category_label: str) -> dict:
    """Inspect the body for an H2 introduction heading containing the exact PN.

    V4.0.4 intentionally accepts natural variants such as ``معرفی 2N7000`` and
    ``معرفی ماسفت 2N7000``. The canonical form is only inserted when no such H2
    exists. This keeps the repair idempotent and does not rewrite acceptable model
    headings.
    """
    pn = str(part_number or '').strip()
    label = str(category_label or 'محصول').strip() or 'محصول'
    expected = f'معرفی {label} {pn}'.strip()
    matches = []
    for line in (md or '').splitlines():
        h = _heading_text(line)
        if not h or h[0] != 2:
            continue
        raw = h[1].strip()
        norm = _fa_heading_normalize(raw)
        if 'معرفی' in norm and pn.casefold() in raw.casefold():
            matches.append(raw)
    return {
        'status': 'PASS' if matches else 'MISSING',
        'expected': expected,
        'found': bool(matches),
        'occurrences': len(matches),
        'matched_headings': matches,
        'programmatic_repair_applied': False,
    }


def ensure_intro_heading(product: dict, md: str) -> tuple[str, dict, list[str]]:
    """Ensure one introduction H2 exists before final validation/HTML rendering.

    This is a deterministic presentation repair. It adds no technical facts and
    makes no model/API call. If an acceptable introduction H2 already exists, the
    body is returned byte-for-byte apart from the terminal newline normalization.
    """
    pn = str(product['identity']['part_number']).strip()
    label = str(product['identity'].get('product_type_label') or '').strip()
    if not label:
        try:
            from core.category_registry import category_record, normalize_category_key
            key = normalize_category_key(product['identity'].get('product_category')) or 'ic'
            rec = category_record(key)
            label = str(rec.get('title_prefix') or rec.get('display_name') or 'محصول').strip()
        except Exception:
            label = 'محصول'

    body = (md or '').strip()
    before = intro_heading_status(body, pn, label)
    if before['found']:
        return body + ('\n' if body else ''), before, []

    canonical = f'## **{before["expected"]}**'
    repaired = canonical if not body else canonical + '\n\n' + body
    # Keep the existing structural convention: every later H2 is separated from
    # the introduction section. Existing separators are preserved without duplication.
    repaired = _ensure_separators(repaired)
    after = intro_heading_status(repaired, pn, label)
    after['programmatic_repair_applied'] = True
    if not after['found']:
        raise RuntimeError(f'INTRO_HEADER_REPAIR_FAILED for {pn}')
    return repaired.strip() + '\n', after, ['intro_header_programmatic_v4_0_4']

def _safe_intro(product: dict) -> str:
    pn = product['identity']['part_number']
    label = (product['identity'].get('product_type_label') or 'قطعه الکترونیکی').strip()
    return f'برای خرید {pn} می‌توانید قیمت و موجودی روز را از توکل الکترونیک استعلام کنید و در صورت نیاز پیش‌فاکتور دریافت کنید.'


def _safe_order_text() -> str:
    return 'برای استعلام قیمت و موجودی روز، ثبت سفارش یا دریافت پیش‌فاکتور با توکل الکترونیک در ارتباط باشید. ضمانت اصالت کالا نیز مطابق شرایط فروشگاه ارائه می‌شود.'


def repair_body_structure(product: dict, md: str) -> tuple[str, list[str]]:
    """Deterministic, fact-free repairs for presentation-only contract failures.

    This layer may add only commercial boilerplate based on verified identity/store
    rules. It never invents technical specifications.
    """
    pn = product['identity']['part_number']
    manufacturer = product['identity'].get('manufacturer')
    verified_package = product['identity'].get('verified_package_installation')
    repairs = []
    md = _normalize_headings(md)

    # Known internal field identifiers are presentation artifacts, not customer
    # language. Repair the harmless label deterministically instead of buying a
    # model retry. Safety validation still blocks any other internal leakage.
    cleaned = re.sub(r'\bpackage_installation\b', 'پکیج / نصب', md, flags=re.I)
    if cleaned != md:
        md = cleaned
        repairs.append('internal_package_label_cleanup')

    # Ensure the exact PN appears naturally near the start for SEO, without
    # changing any technical claim.
    head = md[:500].casefold()
    if pn.casefold() not in head:
        md = _safe_intro(product) + '\n\n' + md
        repairs.append('safe_intro_with_exact_pn')

    h2, h3 = _heading_sets(md)
    if not any(('خرید' in x or 'قیمت' in x) for x in h2):
        md = _append_section(md, f'''## **خرید و قیمت {pn}**\n\n{_safe_order_text()}''')
        repairs.append('purchase_price_section')

    md, faq_merge_repairs = merge_duplicate_faq_sections(md)
    repairs.extend(faq_merge_repairs)
    h2, h3 = _heading_sets(md)
    faq_present = any(_is_faq_title(x) for x in h2)
    if faq_present and len(h3) < 2:
        md, inserted = _insert_faq_questions_into_existing(md, pn)
        if inserted:
            repairs.append('faq_questions_completed_in_existing_section')
    elif not faq_present:
        faq = f'''## **سوالات متداول**\n\n### **چطور {pn} را سفارش دهم؟**\n\nبرای سفارش، ابتدا پارت‌نامبر را با قطعه موردنیاز خود تطبیق دهید و سپس قیمت و موجودی روز را استعلام کنید.\n\n### **پیش از خرید چه مواردی را بررسی کنم؟**\n\nکد دقیق قطعه، برند در صورت مشخص بودن و اطلاعات روی قطعه یا مدار را بررسی کنید تا احتمال سفارش اشتباه کاهش پیدا کند.'''
        md = _append_section(md, faq)
        repairs.append('faq_section')

    h2, h3 = _heading_sets(md)
    if not any(('جمع' in x or 'سفارش' in x or 'نتیجه' in x) for x in h2):
        md = _append_section(md, f'''## **جمع‌بندی و سفارش**\n\n{_safe_order_text()}''')
        repairs.append('closing_order_section')

    if not _has_table(md):
        rows = [
            ('پارت‌نامبر', pn),
            ('برند', manufacturer or 'نیازمند تأیید'),
            ('پکیج / نصب', verified_package or 'نیازمند تأیید'),
            ('وضعیت خرید', 'استعلام قیمت و موجودی روز'),
        ]
        table = '## **اطلاعات سفارش**\n\n| مورد | اطلاعات |\n|---|---|\n' + '\n'.join(f'| {a} | {b} |' for a, b in rows)
        md = _append_section(md, table)
        repairs.append('safe_identity_table')

    md2 = _normalize_headings(md)
    if md2 != md:
        repairs.append('bold_heading_normalization')
    md = _ensure_separators(md2)
    return md.strip() + '\n', repairs


def repair_snippet_and_alts(product: dict, agent: dict) -> tuple[dict, list[str]]:
    """Deterministic fixes for fields that must never require a full LLM retry."""
    out = dict(agent)
    repairs = []
    pn = product['identity']['part_number']
    label = product['identity'].get('product_type_label') or 'محصول'

    title = str(out.get('seo_title') or '').strip()
    pos = title.casefold().find(pn.casefold())
    if pos < 0 or (title and pos >= max(1, len(title) // 2)):
        out['seo_title'] = f'{pn} | خرید، قیمت و موجودی'
        repairs.append('seo_title_exact_pn_start')

    meta = str(out.get('meta_description') or '').strip()
    if pn.casefold() not in meta.casefold():
        out['meta_description'] = (
            f'برای خرید {pn}، استعلام قیمت و موجودی روز و دریافت پیش‌فاکتور با توکل الکترونیک در ارتباط باشید. '
            'پیش از سفارش، پارت‌نامبر را بررسی کنید.'
        )
        repairs.append('meta_exact_pn')

    # Product title is the WooCommerce H1 and must contain exact PN.
    from core.category_registry import product_title
    expected_title = product_title(pn, product['identity'].get('product_category'))
    if str(out.get('product_title') or '').strip() != expected_title:
        out['product_title'] = expected_title
        repairs.append('product_title_programmatic_v3')

    return out, repairs


def _is_faq_title(text: str) -> bool:
    t = (text or '').casefold().replace('ي','ی').replace('ك','ک').replace('ؤ','و').replace('‌',' ')
    t = re.sub(r'\s+', ' ', t).strip()
    return ('سوالات متداول' in t) or ('پرسش' in t) or ('faq' in t)


def _split_h2_sections(md: str):
    lines = (md or '').splitlines()
    prefix, sections, cur = [], [], None
    for line in lines:
        h = _heading_text(line)
        if h and h[0] == 2:
            if cur is not None:
                sections.append(cur)
            cur = [line]
        elif cur is None:
            prefix.append(line)
        else:
            cur.append(line)
    if cur is not None:
        sections.append(cur)
    return prefix, sections


def _dedupe_faq_h3_lines(lines):
    out, seen = [], set()
    skip = False
    for line in lines:
        h = _heading_text(line)
        if h and h[0] == 3:
            key = re.sub(r'\s+', ' ', h[1].casefold()).strip()
            if key in seen:
                skip = True
                continue
            seen.add(key)
            skip = False
        elif h and h[0] == 2:
            skip = False
        if not skip:
            out.append(line)
    return out


def merge_duplicate_faq_sections(md: str) -> tuple[str, list[str]]:
    """Merge multiple FAQ H2 sections before Tone Editor without adding facts."""
    prefix, sections = _split_h2_sections(md)
    faq_idxs = []
    for i, sec in enumerate(sections):
        h = _heading_text(sec[0]) if sec else None
        if h and _is_faq_title(h[1]):
            faq_idxs.append(i)
    if len(faq_idxs) <= 1:
        return (md or '').strip() + '\n', []

    first = faq_idxs[0]
    merged = [sections[first][0]]
    for idx in faq_idxs:
        merged.extend(sections[idx][1:])
        if merged and merged[-1].strip():
            merged.append('')
    merged = _dedupe_faq_h3_lines(merged)
    new_sections = []
    for i, sec in enumerate(sections):
        if i == first:
            new_sections.append(merged)
        elif i in faq_idxs:
            continue
        else:
            new_sections.append(sec)
    lines = list(prefix)
    for sec in new_sections:
        lines.extend(sec)
    return '\n'.join(lines).strip() + '\n', ['duplicate_faq_sections_merged']


def _insert_faq_questions_into_existing(md: str, pn: str) -> tuple[str, bool]:
    prefix, sections = _split_h2_sections(md)
    for i, sec in enumerate(sections):
        h = _heading_text(sec[0]) if sec else None
        if not h or not _is_faq_title(h[1]):
            continue
        existing = sum(1 for line in sec if (_heading_text(line) or (None,))[0] == 3)
        if existing >= 2:
            return md, False
        needed = []
        if existing == 0:
            needed.extend([
                f'### **چطور {pn} را سفارش دهم؟**', '',
                'برای سفارش، ابتدا پارت‌نامبر را با قطعه موردنیاز خود تطبیق دهید و سپس قیمت و موجودی روز را استعلام کنید.', '',
            ])
        needed.extend([
            '### **پیش از خرید چه مواردی را بررسی کنم؟**', '',
            'کد دقیق قطعه و اطلاعات واقعی روی قطعه یا مدار را بررسی کنید تا احتمال سفارش اشتباه کاهش پیدا کند.'
        ])
        sec.extend([''] + needed)
        sections[i] = sec
        lines = list(prefix)
        for x in sections:
            lines.extend(x)
        return '\n'.join(lines).strip(), True
    return md, False


def repair_high_keyword_density(md: str, part_number: str, target_max: float = 1.5, replacement_phrase: str = "این آی سی") -> tuple[str, list[str]]:
    """Reduce excessive exact-PN density with programmatic prose-only replacements.

    Frozen Altimate V1 inherited local-normalizer policy:
    - Run only when exact-PN density is above the configured maximum.
    - Never touch Markdown headings (H1-H6), tables, links, code-like lines, or
      separators. Only plain explanatory prose is eligible.
    - Every exact-PN occurrence in plain explanatory prose is eligible; headings
      remain untouched, which preserves the structural SEO occurrences.
    - Choose replacement locations in a pseudo-random order and
      replace only as many as needed with the literal Persian phrase ``این IC``.
    - The pseudo-random order is seeded from PN+content so a given candidate is
      reproducible/auditable while the selected prose occurrences are dispersed.
    """
    import hashlib
    import random
    from phase3b_validator.markdown_tools import words, strip_markdown
    from phase3b_validator.metrics import count_exact

    text = md or ''

    def density(x: str) -> float:
        w = len(words(x))
        return (count_exact(strip_markdown(x), part_number) / w * 100.0) if w else 0.0

    if not len(words(text)) or density(text) <= float(target_max):
        return text, []

    lines = text.splitlines()
    eligible = []

    # Collect exact-PN occurrences only from plain explanatory prose.
    for line_idx, line in enumerate(lines):
        st = line.strip()
        if (
            not st
            or st.startswith('#')
            or st.startswith('|')
            or st.startswith('>')
            or st.startswith(('-', '*', '+'))
            or st in {'---', '***', '___'}
            or '](' in line
            or '`' in line
            or '<' in line and '>' in line
        ):
            continue
        matches = list(re.finditer(re.escape(part_number), line, flags=re.I))
        for m in matches:
            eligible.append((line_idx, m.start(), m.end()))

    if not eligible:
        return text, []

    # Random-looking but reproducible selection for auditability/tests.
    seed_material = (part_number + '\n' + text).encode('utf-8')
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], 'big')
    rng = random.Random(seed)
    rng.shuffle(eligible)

    repairs = 0
    # Replace one occurrence at a time, then recompute density because ``این IC``
    # changes both exact-PN count and word count. Rebuild line offsets each time
    # from the selected original line index to avoid stale character positions.
    for line_idx, original_start, _original_end in eligible:
        if density('\n'.join(lines)) <= float(target_max):
            break
        line = lines[line_idx]
        matches = list(re.finditer(re.escape(part_number), line, flags=re.I))
        if not matches:
            continue
        # Select the surviving match whose start is closest to the original slot.
        m = min(matches, key=lambda x: abs(x.start() - original_start))
        line = line[:m.start()] + replacement_phrase + line[m.end():]
        lines[line_idx] = line
        repairs += 1

    out = '\n'.join(lines).strip() + '\n'
    return out, (['deterministic_high_keyword_density_repair_category_aware'] if repairs else [])


def remove_duplicate_sentences(md: str) -> tuple[str, list[str]]:
    """Remove exact repeated prose sentences; headings/tables/links are untouched."""
    seen, changed, out = set(), False, []
    for line in (md or '').splitlines():
        st = line.strip()
        if not st or st.startswith('#') or st.startswith('|') or st in {'---','***','___'} or '](' in line:
            out.append(line); continue
        parts = re.split(r'(?<=[.!؟])\s+', line)
        kept = []
        for sentence in parts:
            key = re.sub(r'\s+', ' ', sentence.casefold()).strip()
            if len(key) >= 35 and key in seen:
                changed = True
                continue
            if len(key) >= 35:
                seen.add(key)
            kept.append(sentence)
        out.append(' '.join(kept).strip())
    return '\n'.join(out).strip() + '\n', (['exact_duplicate_sentences_removed'] if changed else [])


def remove_repeated_part_number_warnings(md: str) -> tuple[str, list[str]]:
    """Keep only the first generic PN-check warning outside protected sections.

    Altimate V1 never removes closing/CTA content and never removes link/table/heading
    blocks. This preserves the empty-summary regression fix inherited from the prior branch.
    """
    blocks = re.split(r'(\n\s*\n)', md or '')
    seen_warning = False
    changed = False
    out = []
    current_h2 = ''
    for block in blocks:
        st = block.strip()
        if not st or block.isspace():
            out.append(block); continue
        h = _heading_text(st) if '\n' not in st else None
        if h and h[0] == 2:
            current_h2 = h[1]
            out.append(block); continue
        if st.startswith('#') or st.startswith('|') or '](' in block:
            out.append(block); continue
        # Closing/CTA paragraphs are mandatory and must never be removed here.
        if any(x in current_h2 for x in ('جمع', 'نتیجه', 'سفارش')):
            out.append(block); continue
        norm = st.casefold().replace('‌',' ')
        is_warning = (
            ('پارت' in norm or 'کد دقیق قطعه' in norm or 'شماره قطعه' in norm)
            and ('تطبیق' in norm or 'بررسی' in norm)
            and ('سفارش' in norm or 'خرید' in norm)
        )
        if is_warning:
            if seen_warning:
                changed = True
                continue
            seen_warning = True
        out.append(block)
    return ''.join(out).strip() + '\n', (['repeated_part_number_warning_removed'] if changed else [])


def cleanup_banned_style_phrases(md: str) -> tuple[str, list[str]]:
    """Altimate V1 deterministic cleanup for known customer-facing meta phrases.

    This is deletion/wording normalization only; it never adds a technical fact.
    It is safe to run after Tone Editor because it does not insert sections,
    links, facts, values or claims.
    """
    text = md or ''
    original = text
    replacements = [
        (r'\bدر\s+این\s+صفحه\b', ''),
        (r'بر\s+اساس\s+داده(?:‌|\s)*(?:های)?\s*(?:مجاز|تأیید(?:شده)?|استخراج(?:شده)?)\s*[،,:؛-]*', ''),
        (r'جدول\s+زیر\s+مهم(?:‌|\s)*ترین\s+(?:Facts|فکت(?:‌|\s)*های?)\s+فنی\s+[^.!؟]*[.!؟]?', ''),
        (r'این\s+جدول\s+برای\s+مرور\s+سریع\s+مشخصات\s+اصلی\s+تهیه\s+شده\s+است[؛،,:-]*', ''),
    ]
    for pat, repl in replacements:
        text = re.sub(pat, repl, text, flags=re.I)
    # Repair whitespace/punctuation left by phrase deletion without touching URLs.
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'(?m)^\s+|\s+$', lambda m: '' if '\n' not in m.group(0) else m.group(0), text)
    text = re.sub(r'\s+([،؛.!؟])', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n', (['deterministic_banned_style_phrase_cleanup'] if text.strip() != original.strip() else [])


def _first_sentence(text: str) -> str:
    st = (text or '').strip()
    if not st:
        return ''
    parts = re.split(r'(?<=[.!؟])\s+', st, maxsplit=1)
    return parts[0].strip()


def _normalize_faq_title_text(text: str) -> str:
    t = (text or '').casefold().replace('ي', 'ی').replace('ك', 'ک').replace('ؤ', 'و')
    t = t.replace('\u200c', ' ')
    return re.sub(r'\s+', ' ', t).strip()


def _limit_faq_to_two_questions(md: str) -> tuple[str, list[str]]:
    """Keep at most the first two FAQ H3 questions and their answers."""
    lines = (md or '').splitlines()
    out = []
    in_faq = False
    faq_q = 0
    dropping = False
    changed = False
    for line in lines:
        h = _heading_text(line)
        if h and h[0] == 2:
            in_faq = _is_faq_title(h[1])
            faq_q = 0
            dropping = False
            out.append(line)
            continue
        if in_faq and h and h[0] == 3:
            faq_q += 1
            dropping = faq_q > 2
            if dropping:
                changed = True
                continue
        if in_faq and dropping:
            # drop answer content until the next H3/H2 (handled above)
            continue
        out.append(line)
    return '\n'.join(out).strip() + '\n', (['faq_limited_to_two_questions'] if changed else [])


def _compress_purchase_section(md: str, part_number: str) -> tuple[str, list[str]]:
    """Compress repetitive sales prose while preserving tables and policy links."""
    prefix, sections = _split_h2_sections(md)
    changed = False
    for i, sec in enumerate(sections):
        h = _heading_text(sec[0]) if sec else None
        if not h:
            continue
        title = h[1].strip()
        is_purchase = ('قیمت' in title) or ('استعلام' in title) or ('موجودی' in title) or title.startswith('خرید')
        if not is_purchase:
            continue
        # Preserve any table and any paragraph containing a Markdown link.
        preserved = [sec[0], '']
        link_lines = []
        table_lines = []
        in_table = False
        for line in sec[1:]:
            st = line.strip()
            if st.startswith('|'):
                table_lines.append(line); in_table = True
            elif in_table and not st:
                table_lines.append(line)
            else:
                in_table = False
                if '](' in line:
                    link_lines.append(line)
        concise = (
            f'برای خرید {part_number}، استعلام قیمت و موجودی روز، ثبت سفارش یا دریافت پیش‌فاکتور '
            'با توکل الکترونیک در ارتباط باشید. ضمانت اصالت کالا مطابق شرایط فروشگاه ارائه می‌شود.'
        )
        preserved.append(concise)
        if link_lines:
            preserved.extend([''] + link_lines)
        if table_lines:
            preserved.extend([''] + table_lines)
        new_sec = preserved
        if '\n'.join(new_sec).strip() != '\n'.join(sec).strip():
            sections[i] = new_sec
            changed = True
    if not changed:
        return md, []
    lines = list(prefix)
    for sec in sections:
        lines.extend(sec)
    return '\n'.join(lines).strip() + '\n', ['purchase_section_concise_normalization']


def _truncate_summary_paragraph(md: str) -> tuple[str, list[str]]:
    prefix, sections = _split_h2_sections(md)
    changed = False
    for i, sec in enumerate(sections):
        h = _heading_text(sec[0]) if sec else None
        if not h or not (('جمع' in h[1]) or ('نتیجه' in h[1]) or ('سفارش' in h[1])):
            continue
        # Keep heading and truncate the first prose paragraph to two sentences max.
        body = '\n'.join(sec[1:]).strip()
        if not body:
            continue
        blocks = re.split(r'\n\s*\n', body)
        new_blocks = []
        prose_done = False
        for b in blocks:
            st = b.strip()
            if not st:
                continue
            if not prose_done and not st.startswith(('#', '|')) and '](' not in st:
                sentences = re.split(r'(?<=[.!؟])\s+', st)
                compact = ' '.join(sentences[:2]).strip()
                new_blocks.append(compact)
                prose_done = True
            else:
                new_blocks.append(st)
        new_sec = [sec[0], ''] + [x for j, b in enumerate(new_blocks) for x in (([b, ''] if j < len(new_blocks)-1 else [b]))]
        if '\n'.join(new_sec).strip() != '\n'.join(sec).strip():
            sections[i] = new_sec
            changed = True
    if not changed:
        return md, []
    lines = list(prefix)
    for sec in sections:
        lines.extend(sec)
    return '\n'.join(lines).strip() + '\n', ['summary_paragraph_trimmed']


def _remove_low_value_nontechnical_paragraph(md: str, part_number: str = "") -> tuple[str, bool]:
    """Remove one low-value nontechnical prose block, preserving links/numbers/sections."""
    from phase3b_validator.markdown_tools import words
    blocks = re.split(r'(\n\s*\n)', md or '')
    current_h2 = ''
    candidates = []
    prose_by_section = {}
    for idx, block in enumerate(blocks):
        st = block.strip()
        if not st or block.isspace():
            continue
        h = _heading_text(st.splitlines()[0]) if '\n' not in st or st.startswith('#') else None
        if h and h[0] == 2:
            current_h2 = h[1]
            continue
        if st.startswith(('#', '|')) or '](' in st or '`' in st:
            continue
        sec_key = current_h2 or '__PREFIX__'
        # Count all prose blocks so deleting one generic paragraph is allowed
        # when another (possibly technical) paragraph keeps the section non-empty.
        prose_by_section[sec_key] = prose_by_section.get(sec_key, 0) + 1
        # Never delete technical/numeric prose. Ignore digits that belong only
        # to the exact part number when deciding whether prose is technical.
        tech_probe = re.sub(re.escape(part_number), '', st, flags=re.I) if part_number else st
        if re.search(r'\d|(?:\bV\b|mA|\bA\b|ns|MHz|kHz|dB|°C|VDD|VSS|VIN|VOH|VOL)', tech_probe, re.I):
            continue
        score = 0
        norm = st.casefold().replace('\u200c',' ')
        if any(x in current_h2 for x in ('معرفی', 'خرید', 'قیمت', 'جمع', 'سفارش')): score += 4
        if any(x in norm for x in ('پارت نامبر', 'پارت‌نامبر', 'ثبت سفارش', 'استعلام', 'انتخاب قطعه', 'بررسی قطعه')): score += 3
        score += min(3, len(words(st)) // 30)
        candidates.append((score, idx, sec_key))
    if not candidates:
        return md, False
    # Remove only if the section retains another prose block, except prefix where first block is protected.
    for _score, idx, sec in sorted(candidates, reverse=True):
        if prose_by_section.get(sec, 0) <= 1:
            continue
        blocks[idx] = ''
        return ''.join(blocks).strip() + '\n', True
    return md, False


def repair_excessive_word_count(
    md: str,
    part_number: str,
    *,
    hard_max: int,
    target_max: int | None = None,
) -> tuple[str, list[str]]:
    """Conservative Altimate V1 local length normalizer.

    It removes/compresses only low-value presentation/sales repetition. Numeric
    technical prose, tables, Markdown links and headings are protected. The goal
    is to get below ``hard_max`` without buying another LLM call.
    """
    from phase3b_validator.markdown_tools import words
    text = (md or '').strip() + '\n'
    if len(words(text)) <= int(hard_max):
        return text, []
    repairs = []
    for fn in (merge_duplicate_faq_sections, _limit_faq_to_two_questions, remove_duplicate_sentences, remove_repeated_part_number_warnings):
        text2, rs = fn(text)
        text = text2; repairs.extend(rs)
    text2, rs = cleanup_banned_style_phrases(text)
    text = text2; repairs.extend(rs)

    if len(words(text)) > hard_max:
        text2, rs = _compress_purchase_section(text, part_number)
        text = text2; repairs.extend(rs)
    if len(words(text)) > hard_max:
        text2, rs = _truncate_summary_paragraph(text)
        text = text2; repairs.extend(rs)

    # Re-establish H2 boundaries before paragraph pruning so a prose block can
    # never accidentally absorb/delete the following heading.
    text = _ensure_separators(text)

    # Remove one low-value nontechnical paragraph at a time. Stop at a small
    # buffer below the hard ceiling so a later Tone edit is less likely to cross it.
    stop_at = int(target_max if target_max is not None else max(1, hard_max - 20))
    stop_at = min(stop_at, int(hard_max) - 10) if hard_max > 20 else stop_at
    guard = 0
    while len(words(text)) > stop_at and guard < 12:
        text2, changed = _remove_low_value_nontechnical_paragraph(text, part_number)
        if not changed:
            break
        text = text2
        repairs.append('low_value_nontechnical_paragraph_removed')
        guard += 1

    text = _ensure_separators(text)
    return text.strip() + '\n', (repairs or [])



def _fine_compress_purchase_section(md: str, part_number: str) -> tuple[str, list[str]]:
    """Near-ceiling deletion/compression using only safe store language.

    Preserves headings, Markdown links and tables. It is intentionally more
    concise than the normal purchase normalizer and is used only when a page is
    a few words above the hard word-count ceiling.
    """
    prefix, sections = _split_h2_sections(md)
    changed = False
    for i, sec in enumerate(sections):
        h = _heading_text(sec[0]) if sec else None
        if not h:
            continue
        title = h[1].strip()
        is_purchase = ('قیمت' in title) or ('استعلام' in title) or ('موجودی' in title) or title.startswith('خرید')
        if not is_purchase:
            continue
        link_lines, table_lines = [], []
        in_table = False
        for line in sec[1:]:
            st = line.strip()
            if st.startswith('|'):
                table_lines.append(line); in_table = True
            elif in_table and not st:
                table_lines.append(line)
            else:
                in_table = False
                if '](' in line:
                    link_lines.append(line)
        concise = f'برای استعلام قیمت و موجودی روز {part_number} با توکل الکترونیک در ارتباط باشید.'
        new_sec = [sec[0], '', concise]
        if link_lines:
            new_sec.extend([''] + link_lines)
        if table_lines:
            new_sec.extend([''] + table_lines)
        if '\n'.join(new_sec).strip() != '\n'.join(sec).strip():
            sections[i] = new_sec
            changed = True
    if not changed:
        return md, []
    lines = list(prefix)
    for sec in sections:
        lines.extend(sec)
    return '\n'.join(lines).strip() + '\n', ['fine_length_purchase_trim']


def fine_trim_near_word_ceiling(
    md: str,
    part_number: str,
    *,
    hard_max: int,
    margin_words: int = 30,
) -> tuple[str, list[str]]:
    """Fine Altimate V1 trim for content only slightly above the hard ceiling.

    It never rewrites numeric/technical prose. The first tactic is a concise
    purchase-section normalization; if still needed it removes one low-value
    nontechnical paragraph at a time.
    """
    from phase3b_validator.markdown_tools import words
    text = (md or '').strip() + '\n'
    wc = len(words(text))
    if wc <= int(hard_max) or wc > int(hard_max) + int(margin_words):
        return text, []

    repairs = []
    text2, rs = _fine_compress_purchase_section(text, part_number)
    text = text2; repairs.extend(rs)

    guard = 0
    while len(words(text)) > int(hard_max) and guard < 4:
        text2, changed = _remove_low_value_nontechnical_paragraph(text, part_number)
        if not changed:
            break
        text = text2
        repairs.append('fine_length_low_value_paragraph_removed')
        guard += 1

    text = _ensure_separators(text)
    return text.strip() + '\n', repairs

def repair_empty_sections(product: dict, md: str) -> tuple[str, list[str]]:
    """Repair/remove empty headings before Tone Editor using fact-free text only."""
    pn = product['identity']['part_number']
    lines = (md or '').splitlines()
    repairs = []

    def has_content_after(idx: int, level: int) -> bool:
        j = idx + 1
        while j < len(lines):
            h = _heading_text(lines[j])
            if h and h[0] <= level:
                break
            st = lines[j].strip()
            if st and st not in {'---','***','___'} and not (h is not None):
                return True
            j += 1
        return False

    # Work backwards so insertions/removals do not invalidate pending indexes.
    current_faq_ranges = []
    faq = False
    for i, line in enumerate(lines):
        h = _heading_text(line)
        if h and h[0] == 2:
            faq = _is_faq_title(h[1])
        current_faq_ranges.append(faq)

    for i in range(len(lines)-1, -1, -1):
        h = _heading_text(lines[i])
        if not h:
            continue
        level, title = h
        if level not in (2,3) or has_content_after(i, level):
            continue
        if level == 2:
            is_purchase = ('قیمت' in title) or ('استعلام' in title) or ('موجودی' in title) or title.strip().startswith('خرید')
            is_cta = ('جمع' in title) or ('نتیجه' in title) or ('سفارش' in title)
            if is_purchase or is_cta:
                lines[i+1:i+1] = ['', _safe_order_text(), '']
                repairs.append('empty_required_h2_filled_with_safe_store_text')
            else:
                # Non-required empty H2 adds no customer value.
                del lines[i]
                repairs.append('empty_nonrequired_h2_removed')
        else:  # H3
            in_faq = current_faq_ranges[i] if i < len(current_faq_ranges) else False
            if in_faq:
                if ('قیمت' in title) or ('موجودی' in title):
                    answer = f'برای اطلاع از قیمت و موجودی روز {pn}، از توکل الکترونیک استعلام بگیرید.'
                elif ('پارت' in title) or ('سفارش' in title):
                    answer = 'پیش از ثبت سفارش، پارت‌نامبر را با درخواست خرید خود تطبیق دهید.'
                else:
                    answer = 'برای دریافت اطلاعات سفارش و موجودی روز با توکل الکترونیک در ارتباط باشید.'
                lines[i+1:i+1] = ['', answer, '']
                repairs.append('empty_faq_answer_filled_with_safe_store_text')
            else:
                del lines[i]
                repairs.append('empty_nonrequired_h3_removed')
    out = _ensure_separators('\n'.join(lines))
    return out.strip() + '\n', repairs
