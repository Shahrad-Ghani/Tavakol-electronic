"""Best-effort API usage/cost accounting for Phase 1 Final V1.5.

Costs are estimates derived from API-reported token usage and a versioned pricing
snapshot. They are useful for operational monitoring but are not a replacement
for the OpenAI billing dashboard/invoice.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


PRICING_REFERENCE = "2026-08-15-openai-standard"
CURRENCY = "USD"

# USD per 1M tokens. Keep these versioned rather than silently changing history.
_PRICING = {
    "gpt-5.4-nano": {
        "input": 0.20,
        "output": 1.25,
    },
    "gpt-image-2": {
        "text_input": 5.00,
        "image_input": 8.00,
        "image_output": 30.00,
    },
    # Optional legacy economy route. It is kept only for historical reference because the
    # current model catalog marks this model deprecated.
    "gpt-image-1-mini": {
        "text_input": 2.00,
        "image_input": 2.50,
        "image_output": 8.00,
    },
}


def _model_family(model: str | None) -> str | None:
    model = str(model or "")
    if model.startswith("gpt-5.4-nano"):
        return "gpt-5.4-nano"
    if model.startswith("gpt-image-2"):
        return "gpt-image-2"
    if model.startswith("gpt-image-1-mini"):
        return "gpt-image-1-mini"
    return None


def _dump_obj(obj: Any) -> dict | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return deepcopy(obj)
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except TypeError:
            return obj.model_dump()
    # Conservative fallback for SDK objects.
    keys = (
        "input_tokens", "output_tokens", "total_tokens",
        "input_tokens_details", "output_tokens_details",
    )
    out = {}
    for key in keys:
        if hasattr(obj, key):
            value = getattr(obj, key)
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            out[key] = value
    return out or None


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def estimate_cost_usd(model: str, usage: dict | None) -> float | None:
    """Estimate cost from API-reported usage. Returns None if usage is absent/unsupported."""
    if not usage:
        return None
    family = _model_family(model)
    prices = _PRICING.get(family or "")
    if not prices:
        return None

    if family == "gpt-5.4-nano":
        inp = _num(usage.get("input_tokens"))
        out = _num(usage.get("output_tokens"))
        return round((inp * prices["input"] + out * prices["output"]) / 1_000_000, 8)

    in_details = usage.get("input_tokens_details") or {}
    out_details = usage.get("output_tokens_details") or {}
    text_in = _num(in_details.get("text_tokens"))
    image_in = _num(in_details.get("image_tokens"))
    image_out = _num(out_details.get("image_tokens"))

    # Some SDK/API variants may omit output_tokens_details while still reporting
    # output_tokens. For image-only output, treat total output tokens as image.
    if image_out == 0:
        image_out = _num(usage.get("output_tokens"))

    # If details are unavailable, total input cannot safely be split between
    # image/text rates. Do not manufacture a cost estimate.
    if text_in == 0 and image_in == 0 and _num(usage.get("input_tokens")) > 0:
        return None

    cost = (
        text_in * prices["text_input"]
        + image_in * prices["image_input"]
        + image_out * prices["image_output"]
    ) / 1_000_000
    return round(cost, 8)


def from_response(model: str, response: Any) -> dict:
    usage = _dump_obj(getattr(response, "usage", None))
    return {
        "model": model,
        "pricing_reference": PRICING_REFERENCE,
        "currency": CURRENCY,
        "usage": usage,
        "estimated_cost_usd": estimate_cost_usd(model, usage),
    }


def new_accounting_record() -> dict:
    return {
        "pricing_reference": PRICING_REFERENCE,
        "currency": CURRENCY,
        "precheck": {"history": [], "estimated_cost_usd": 0.0},
        "regeneration": {"history": [], "estimated_cost_usd": 0.0},
        "identity_validation": {"history": [], "estimated_cost_usd": 0.0},
        "ocr": {"history": [], "estimated_cost_usd": 0.0},
        "estimated_total_usd": 0.0,
        "note": "Estimated from API-reported usage; billing dashboard is authoritative.",
    }


def record_stage(data: dict, stage: str, accounting: dict | None) -> None:
    """Append one successful API response accounting record and refresh totals."""
    if not accounting:
        return
    root = data.setdefault("diagnostics", {}).setdefault("api_accounting", new_accounting_record())
    section = root.setdefault(stage, {"history": [], "estimated_cost_usd": 0.0})
    section.setdefault("history", []).append(accounting)

    known = [x.get("estimated_cost_usd") for x in section["history"] if x.get("estimated_cost_usd") is not None]
    section["estimated_cost_usd"] = round(sum(float(x) for x in known), 8) if known else None

    stage_costs = []
    any_unknown = False
    for name in ("precheck", "regeneration", "identity_validation", "ocr"):
        s = root.get(name, {})
        hist = s.get("history") or []
        if hist and s.get("estimated_cost_usd") is None:
            any_unknown = True
        elif s.get("estimated_cost_usd") is not None:
            stage_costs.append(float(s.get("estimated_cost_usd") or 0))
    root["estimated_total_usd"] = None if any_unknown else round(sum(stage_costs), 8)
