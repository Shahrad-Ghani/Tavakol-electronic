from __future__ import annotations

import json
import os
from pathlib import Path

from core.category_registry import category_context


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
        payload = {
            "TARGET_PART_NUMBER": part_number,
            "CATEGORY_CONTEXT": category_context(category_key),
            "VERIFIED_MANUFACTURER": manufacturer,
            "SAFE_FACTS_OPTIONAL": safe_facts,
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
        ctx = category_context(category_key)
        title = f"خرید {ctx['display_name']} {part_number} | قیمت و موجودی"
        meta = f"برای خرید {ctx['display_name']} {part_number}، قیمت و موجودی روز را بررسی کنید و برای استعلام، سفارش یا دریافت پیش‌فاکتور با توکل الکترونیک در ارتباط باشید."
        return {"seo_title": title, "meta_description": meta}, {"provider":"local-mock","model":"deterministic-v4","usage":None}
