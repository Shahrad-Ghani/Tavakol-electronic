import re

from .normalization import lower

PN_TOKEN = re.compile(r"\b[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+\b|\b[A-Za-z]{1,8}\d[A-Za-z0-9-]{2,}\b")


def _compact(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', lower(value or ''))


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _looks_like_target_variant(expected: str, found: str) -> bool:
    e = _compact(expected)
    f = _compact(found)
    if not e or not f or e == f:
        return False
    # Obvious truncation/extension remains a hard fail.
    if min(len(e), len(f)) >= 5 and (e.startswith(f) or f.startswith(e)):
        return True
    # V4.1: catch sibling suffix substitutions such as TC426MJA -> TC426CPA.
    # Require a substantial exact prefix to avoid fuzzy/semantic matching.
    shared = _common_prefix_len(e, f)
    return shared >= 5 and shared >= min(len(e), len(f)) * 0.5


def part_number_integrity(bundle: dict, md: str) -> dict:
    """Scoreless absolute identity gate; never changes RankMath calibration score."""
    expected = bundle["identity"]["part_number"]
    fields = {
        "page.product_title": bundle["page"].get("product_title", ""),
        "snippet.seo_title": bundle["snippet"].get("seo_title", ""),
        "snippet.meta_description": bundle["snippet"].get("meta_description", ""),
        # V4 slug is deterministic and category-aware (e.g. tc427cpa-ic),
        # so it is not a free-form identity source. Identity is gated on the
        # model-authored title/snippet/body fields below.
        "content.markdown": md,
    }
    expected_l = lower(expected)
    suspicious = []
    seen = set()
    for field, text in fields.items():
        for token in PN_TOKEN.findall(text or ""):
            t = lower(token)
            if t == expected_l:
                continue
            if _looks_like_target_variant(expected, token):
                key = (field, t)
                if key not in seen:
                    seen.add(key)
                    suspicious.append({"field": field, "found": token, "expected": expected})
    return {
        "status": "FAIL" if suspicious else "PASS",
        "severity": "HARD_FAIL" if suspicious else "PASS",
        "evidence": suspicious,
    }
