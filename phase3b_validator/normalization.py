import re
import unicodedata

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-"})


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.translate(_DASHES)
    return re.sub(r"\s+", " ", value).strip()


def lower(value: str) -> str:
    return normalize_text(value).casefold()


def normalize_slug(value: str) -> str:
    value = lower(value).replace("_", "-")
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-/")


def keyword_slug_form(keyword: str) -> str:
    return normalize_slug(keyword)
