import html
import re

_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
_ALLOWED_INLINE_TAGS = ('sub', 'sup', 'br')


def _protect_allowed_inline_html(text: str):
    placeholders = {}
    idx = 0

    def repl(match):
        nonlocal idx
        key = f'\x00HTML{idx}\x00'
        placeholders[key] = match.group(0)
        idx += 1
        return key

    tag_re = re.compile(
        r'</?(?:' + '|'.join(_ALLOWED_INLINE_TAGS) + r')(?:\s*/?)?>',
        flags=re.I,
    )
    return tag_re.sub(repl, text), placeholders


def inline(text: str) -> str:
    # Preserve a tiny safe whitelist used by technical notation (sub/sup/br),
    # and protect Markdown links before escaping the surrounding text.
    protected, placeholders = _protect_allowed_inline_html(text)

    link_placeholders = {}
    link_index = 0

    def protect_link(match):
        nonlocal link_index
        key = f'\x00LINK{link_index}\x00'
        label = html.escape(match.group(1), quote=False)
        href = html.escape(match.group(2), quote=True)
        link_placeholders[key] = f'<a href="{href}">{label}</a>'
        link_index += 1
        return key

    protected = _LINK_RE.sub(protect_link, protected)
    escaped = html.escape(protected, quote=False)
    escaped = _BOLD_RE.sub(r'<strong>\1</strong>', escaped)

    for key, value in placeholders.items():
        escaped = escaped.replace(key, value)
    for key, value in link_placeholders.items():
        escaped = escaped.replace(key, value)
    return escaped


def _split_table_row(line: str):
    """Split a Markdown table row while honoring escaped pipes (\\|)."""
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    cells = []
    buf = []
    escaped = False
    for ch in s:
        if escaped:
            if ch == '|':
                buf.append('|')
            else:
                buf.append('\\')
                buf.append(ch)
            escaped = False
            continue
        if ch == '\\':
            escaped = True
            continue
        if ch == '|':
            cells.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if escaped:
        buf.append('\\')
    cells.append(''.join(buf).strip())
    return cells


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r':?-{3,}:?', c.strip()) for c in cells)


def _normalize_row_width(cells, expected_cols):
    """Recover rows broken by literal |...| technical notation.

    The content-agent sometimes emits values such as |IOUT| inside a 3-column
    Markdown table without escaping them. If that creates extra cells, keep the
    first and last logical columns and merge the accidental middle fragments.
    """
    if expected_cols <= 0 or len(cells) == expected_cols:
        return cells
    if len(cells) < expected_cols:
        return cells + [''] * (expected_cols - len(cells))
    if expected_cols == 1:
        return [' | '.join(cells)]
    if expected_cols == 2:
        return [cells[0], '|'.join(cells[1:])]
    # In Tavakol technical tables, accidental literal pipes (for example
    # |IOUT|) normally occur in the final condition/notes column. Keep the
    # leading logical columns stable and merge overflow back into the last.
    lead = cells[: expected_cols - 1]
    last = '|'.join(cells[expected_cols - 1 :])
    return lead + [last]


def _table_html(rows):
    header = rows[0]
    expected_cols = len(header)
    data_rows = [_normalize_row_width(r, expected_cols) for r in rows[2:]]

    table_style = (
        'width:100%;border-collapse:collapse;direction:rtl;text-align:right;'
        'border:1px solid #e0e0e2;'
    )
    cell_style = (
        'border:1px solid #e0e0e2;padding:8px;vertical-align:top;text-align:right;'
    )
    head_style = cell_style + 'font-weight:700;'

    out = [
        '<figure class="wp-block-table tavakol-content-table" dir="rtl" '
        'style="direction:rtl;overflow-x:auto;">',
        f'<table dir="rtl" style="{table_style}">',
        '<thead><tr>' + ''.join(
            f'<th scope="col" style="{head_style}">{inline(c)}</th>' for c in header
        ) + '</tr></thead>',
        '<tbody>',
    ]
    for row in data_rows:
        out.append('<tr>' + ''.join(
            f'<td style="{cell_style}">{inline(c)}</td>' for c in row
        ) + '</tr>')
    out.extend(['</tbody></table>', '</figure>'])
    return out


def render_html(md: str) -> str:
    lines = md.splitlines()
    out = [
        '<div class="tavakol-product-content" dir="rtl" '
        'style="direction:rtl;text-align:right;">'
    ]
    i = 0
    para = []

    def flush_para():
        nonlocal para
        if para:
            out.append(
                '<p dir="rtl" style="direction:rtl;text-align:right;">'
                + inline(' '.join(x.strip() for x in para))
                + '</p>'
            )
            para = []

    while i < len(lines):
        line = lines[i]
        st = line.strip()
        if not st:
            flush_para()
            i += 1
            continue
        if st == '---':
            flush_para()
            out.append('<hr>')
            i += 1
            continue
        hm = re.match(r'^(#{1,6})\s+(.+)$', st)
        if hm:
            flush_para()
            lvl = len(hm.group(1))
            out.append(
                f'<h{lvl} dir="rtl" style="direction:rtl;text-align:right;">'
                + inline(hm.group(2))
                + f'</h{lvl}>'
            )
            i += 1
            continue
        if (
            st.startswith('|')
            and st.endswith('|')
            and i + 1 < len(lines)
            and lines[i + 1].strip().startswith('|')
            and _is_table_separator(lines[i + 1])
        ):
            flush_para()
            rows = []
            while i < len(lines):
                row_line = lines[i].strip()
                if not (row_line.startswith('|') and row_line.endswith('|')):
                    break
                rows.append(_split_table_row(lines[i]))
                i += 1
            if len(rows) >= 2:
                out.extend(_table_html(rows))
            continue
        para.append(line)
        i += 1

    flush_para()
    out.append('</div>')
    return '\n'.join(out) + '\n'
