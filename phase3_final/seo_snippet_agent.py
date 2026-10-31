from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from core.category_registry import category_context


_TITLE_PATTERNS = (
    "خرید {category} {pn} | استعلام قیمت",
    "سفارش {category} {pn} | مشخصات و موجودی",
    "{category} {pn} | قیمت روز و ثبت سفارش",
    "تهیه {category} {pn} | استعلام و موجودی",
)
_META_PATTERNS = (
    "برای تهیه {category} با کد {pn}، قیمت و موجودی روز را استعلام کنید. امکان بررسی سفارش تکی و تعدادی و دریافت پیش‌فاکتور از توکل الکترونیک فراهم است.",
    "قیمت و شرایط سفارش {category} با پارت‌نامبر {pn} را بررسی کنید. برای اطلاع از موجودی، ثبت سفارش تکی یا تعدادی و دریافت پیش‌فاکتور با توکل الکترونیک تماس بگیرید.",
    "برای استعلام موجودی و قیمت {category} {pn}، کد قطعه و تعداد موردنیاز را اعلام کنید. توکل الکترونیک امکان پیگیری سفارش و ارائه پیش‌فاکتور را فراهم می‌کند.",
    "به دنبال {category} با کد دقیق {pn} هستید؟ برای دریافت قیمت روز، بررسی موجودی و ثبت سفارش تکی یا عمده با توکل الکترونیک در ارتباط باشید.",
)


def _variation_index(part_number: str, count: int) -> int:
    digest = hashlib.sha256(str(part_number).strip().casefold().encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % count


def _verified_fact_labels(safe_facts):
    labels = []
    seen = set()
    if not isinstance(safe_facts, dict):
        return labels
    for fact in safe_facts.get("seo_ready_facts") or []:
        if not isinstance(fact, dict):
            continue
        parameter = " ".join(str(fact.get("parameter") or "").split()).strip()
        if not parameter:
            continue
        key = parameter.casefold()
        if key not in seen:
            seen.add(key)
            labels.append(parameter)
    return labels


def _deterministic_snippet(part_number: str, category_key: str, manufacturer=None, safe_facts=None):
    ctx = category_context(category_key)
    category = str(ctx.get("display_name") or "قطعه الکترونیکی")
    idx = _variation_index(part_number, len(_TITLE_PATTERNS))
    title = _TITLE_PATTERNS[idx].format(category=category, pn=part_number)
    meta = _META_PATTERNS[idx].format(category=category, pn=part_number)
    # Only verified identity and fact labels may influence optional wording.
    # Do not append numerical values or infer a use-case from parameter names.
    if manufacturer:
        meta = meta.replace("توکل الکترونیک", f"سازنده تأییدشده {manufacturer} و توکل الکترونیک", 1)
    return {"seo_title": title, "meta_description": meta}


class SeoSnippetAgent:
    def __init__(self, root: Path, model: str | None = None, client=None):
        self.root = Path(root)
        self.model = model or os.getenv("SEO_SNIPPET_MODEL") or os.getenv("CHEAP_WRITER_MODEL", "gpt-5.6-luna")
        self.schema = json.loads((self.root / "schema" / "seo_snippet.schema.json").read_text(encoding="utf-8"))
        self.instructions = (self.root / "prompts" / "seo_snippet.md").read_text(encoding="utf-8")
        if client is None:
            from orchestrator.api_coordinator import CoordinatedOpenAI as OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.client = client

    def generate(self, *, part_number: str, category_key: str, manufacturer: str | None = None, safe_facts=None):
        idx = _variation_index(part_number, len(_TITLE_PATTERNS))
        payload = {
            "TARGET_PART_NUMBER": part_number,
            "CATEGORY_CONTEXT": category_context(category_key),
            "VERIFIED_MANUFACTURER": manufacturer,
            "SAFE_FACTS_OPTIONAL": safe_facts,
            "VERIFIED_FACT_LABELS": _verified_fact_labels(safe_facts),
            "VARIATION_GUIDANCE": {
                "stable_variant_number": idx + 1,
                "available_variants": len(_TITLE_PATTERNS),
                "instruction": "Choose a natural wording angle for this product; avoid repeating one generic title/meta template across every SKU. The exact PN must appear once in the title and naturally in the description.",
            },
        }
        kwargs = {
            "model": self.model,
            "instructions": self.instructions,
            "input": json.dumps(payload, ensure_ascii=False, indent=2),
            "max_output_tokens": 600,
            "reasoning": {"effort": "low"},
            "text": {"format": {"type": "json_schema", "name": "tavakol_v4_seo_snippet", "schema": self.schema, "strict": True}},
        }
        try:
            r = self.client.responses.create(**kwargs)
        except TypeError:
            kwargs.pop("reasoning", None)
            r = self.client.responses.create(**kwargs)
        data = json.loads(r.output_text)
        usage = getattr(r, "usage", None)
        return data, {"provider":"openai","model":self.model,"response_id":getattr(r,"id",None),"usage":usage.model_dump() if hasattr(usage,"model_dump") else None}


class DeterministicSeoSnippetAgent:
    """Offline/mock-safe substitute used only when the content pipeline is explicitly constructed with mocks."""
    def generate(self, *, part_number: str, category_key: str, manufacturer: str | None = None, safe_facts=None):
        return _deterministic_snippet(part_number, category_key, manufacturer, safe_facts), {
            "provider":"local-mock","model":"deterministic-v5","usage":None,
        }
