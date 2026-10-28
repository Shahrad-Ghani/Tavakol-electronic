import re

# Deterministic guardrails complement the semantic tone editor. They do not
# attempt to detect AI authorship; they catch known customer-facing artifacts.
_PATTERNS = [
    ('FOREIGN_LANGUAGE_LEAKAGE', re.compile(r'\bFunktionsbereich\b', re.I)),
    ('INTERNAL_PIPELINE_LANGUAGE', re.compile(r'\b(?:Validator|Prompt|Keyword\s+Density|Safe\s+Facts|Allowed\s+Facts|source\s+validation)\b', re.I)),
    ('INTERNAL_PIPELINE_LANGUAGE', re.compile(r'\b(?:package_installation|evidence_quote|seo_usage|fact_status)\b', re.I)),
    ('LATEX_LEAKAGE', re.compile(r'\$[^$]+\$|\\text\s*\{', re.I)),
    ('UNNECESSARY_ENGLISH', re.compile(r'\b(?:Operating\s+supply\s+voltage|Operating\s+ambient\s+temperature|Supply\s+current|Function|Package/Installation|Facts)\b', re.I)),
    ('AI_LIKE_META_LANGUAGE', re.compile(r'(?:در\s+این\s+صفحه|بر\s+اساس\s+داده(?:‌|\s)*(?:های)?\s*(?:مجاز|تأیید|استخراج)|جدول\s+زیر\s+.*(?:Facts|فکت))', re.I)),
]


def validate_style_contract(text):
    failures = []
    seen = set()
    for code, rx in _PATTERNS:
        for m in rx.finditer(text or ''):
            key = (code, m.group(0).casefold())
            if key in seen:
                continue
            seen.add(key)
            failures.append({'code': code, 'term': m.group(0)})
    return {'passed': not failures, 'failures': failures}
