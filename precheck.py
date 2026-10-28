from pathlib import Path
import base64
import json
import os
from openai import OpenAI
from api_accounting import from_response as api_accounting_from_response


PRECHECK_PROMPT_VERSION = "v1.2-visual-geometry-profile-selector"

PRECHECK_PROMPT = r"""
You are performing a PRE-REGENERATION VISUAL PROFILE CHECK on ONE reference
photograph of ONE real electronic component.

Your job is NOT to identify the part, improve the image, infer hidden geometry,
or decide whether the image deserves an expensive model.
Use ONLY visible visual evidence in this exact photograph.

The purpose of this check is only to choose conservative anti-hallucination
prompt addendums for the image-editing model.

CLASSIFY ONLY THESE THINGS

1) VISIBLE EXTERNAL PINS / LEADS / TERMINALS
Choose exactly one state:
- "present": one or more external pins/leads/terminals are clearly visible.
- "none": no external pins/leads/terminals are visibly present in this view.
- "uncertain": image evidence is insufficient to confidently choose present or none.

Rules:
- Do not infer pins from package family, brand, printed code, symmetry, electronics
  knowledge, or what may be hidden underneath/behind the component.
- "none" means visually absent in this view, not physically impossible.
- If you can count the clearly visible external pins/leads/terminals with high
  confidence, return the count. Otherwise return null.

2) IRREGULAR / MECHANICALLY UNUSUAL VISIBLE GEOMETRY
Set irregular_geometry=true only when the photograph visibly contains one or
more of these risk features:
- asymmetry
- bent leads
- uneven lead heights
- exposed tabs
- large metal tabs
- partial lead visibility
- irregular mechanical structure
- non-standard body outline
- unusual hole placement
- unusual mounting features

Do not call a package irregular merely because you do not recognize it.
Do not use the printed Part Number or manufacturer to classify package geometry.

CONFIDENCE
Return separate confidence values from 0.0 to 1.0 for the lead-state decision
and the irregular-geometry decision. Confidence must represent visible evidence,
not familiarity with the product.

NOTES
Give one short visual-only note. Do not identify or explain the electronic part.
Do not provide hidden reasoning. Mention only the visible cues that justify the
classification.
""".strip()


PRECHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "visible_leads_state": {
            "type": "string",
            "enum": ["present", "none", "uncertain"],
        },
        "visible_lead_count": {
            "type": ["integer", "null"],
            "minimum": 0,
        },
        "lead_state_confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "irregular_geometry": {"type": "boolean"},
        "irregular_features": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "asymmetry",
                    "bent_leads",
                    "uneven_lead_heights",
                    "exposed_tabs",
                    "large_metal_tabs",
                    "partial_lead_visibility",
                    "irregular_mechanical_structure",
                    "non_standard_body_outline",
                    "unusual_hole_placement",
                    "unusual_mounting_features",
                ],
            },
        },
        "irregular_confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "notes": {"type": ["string", "null"]},
    },
    "required": [
        "visible_leads_state",
        "visible_lead_count",
        "lead_state_confidence",
        "irregular_geometry",
        "irregular_features",
        "irregular_confidence",
        "notes",
    ],
    "additionalProperties": False,
}


def _data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _selected_addendums(result: dict) -> list[str]:
    """Deterministically decide which optional V1.5 prompt addenda are safe to use."""
    threshold = float(os.getenv("PRECHECK_MIN_CONFIDENCE", "0.80"))
    selected = ["commercial_polish"]

    lead_state = result.get("visible_leads_state")
    lead_conf = float(result.get("lead_state_confidence") or 0.0)
    if lead_state == "none" and lead_conf >= threshold:
        selected.insert(0, "pinless")

    irregular = bool(result.get("irregular_geometry"))
    irregular_conf = float(result.get("irregular_confidence") or 0.0)
    if irregular and irregular_conf >= threshold:
        insert_at = len(selected) - 1
        selected.insert(insert_at, "irregular")

    return selected


def _profile_name(selected: list[str]) -> str:
    conditional = [item for item in selected if item != "commercial_polish"]
    return "+".join(conditional) if conditional else "standard"


def derive_routing(result: dict) -> dict:
    """V1.5 is economy-first by design.

    Precheck no longer decides whether the expensive route should be used.
    Every image starts on the cheap primary route, and only a later structural
    validation failure can escalate the image to the strict medium-quality retry.
    """
    selected = _selected_addendums(result)
    return {
        "selected_addendums": selected,
        "prompt_profile": _profile_name(selected),
        "high_risk": False,
        "risk_tier": "economy_first",
        "risk_reasons": [],
        "regeneration_route": "economy-first-primary",
        "recommended_regeneration_model": os.getenv("REGENERATION_PRIMARY_MODEL", os.getenv("REGENERATION_MODEL", "gpt-image-2-2026-04-21")),
        "recommended_regeneration_quality": os.getenv("REGENERATION_PRIMARY_QUALITY", "low"),
    }


def analyze(client: OpenAI, image: Path) -> dict:
    model = os.getenv("PRECHECK_MODEL", "gpt-5.4-nano-2026-03-17")
    detail = os.getenv("PRECHECK_IMAGE_DETAIL", "high")

    response = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": PRECHECK_PROMPT},
                {
                    "type": "input_image",
                    "image_url": _data_url(image),
                    "detail": detail,
                },
            ],
        }],
        text={
            "format": {
                "type": "json_schema",
                "name": "product_image_precheck",
                "strict": True,
                "schema": PRECHECK_SCHEMA,
            }
        },
        max_output_tokens=350,
    )

    if response.status == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
        raise RuntimeError(f"Precheck returned incomplete response: {reason}")

    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("Precheck returned no structured output")

    obj = json.loads(text)

    # Small deterministic consistency normalization. This never guesses geometry.
    state = obj.get("visible_leads_state")
    if state == "none":
        obj["visible_lead_count"] = 0
    elif state == "uncertain":
        obj["visible_lead_count"] = None

    obj.update(derive_routing(obj))
    obj["_api_accounting"] = api_accounting_from_response(model, response)
    return obj
