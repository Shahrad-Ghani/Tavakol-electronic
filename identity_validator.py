from pathlib import Path
import base64
import json
import os
from openai import OpenAI
from api_accounting import from_response as api_accounting_from_response


IDENTITY_VALIDATOR_PROMPT_VERSION = "v2-structural-fallback-gate"

VALIDATOR_PROMPT = r"""
You are performing a POST-REGENERATION COMPARISON between two images of one
real electronic component.

IMAGE A = ORIGINAL REFERENCE PHOTOGRAPH
IMAGE B = REGENERATED CANDIDATE IMAGE

The purpose of this comparison is STRICTLY ECONOMY CONTROL for a fallback image
pipeline. The expensive fallback route should be used only when the candidate
has a fundamental physical identity error.

The candidate is allowed to have:
- a pure white background
- cleaner isolation
- better lighting/exposure
- better sharpness and micro-contrast
- cleaner realistic material rendering
- better ecommerce presentation quality

The candidate is NOT allowed to change the physical identity of the object.

Evaluate these fields:
1. package_geometry = compare body/package outline, proportions, orientation,
   corners, notches, recesses, and overall visible shape.
2. lead_structure = compare visible pins/leads/terminals: visible count when
   comparable, placement, spacing, direction, length, bends, and arrangement.
3. body_color_consistency = compare the dominant visible body/material color
   impression of the component itself. Ignore tiny lighting differences. Mark
   mismatch only if the component has been meaningfully recolored into a visibly
   different object.
4. holes_tabs_features = compare holes, tabs, exposed metal structures, and
   mounting features. Informational only.
5. markings_consistency = compare visible markings. Informational only.
6. invented_or_removed_features = true only when the candidate visibly adds or
   removes a physical feature.
7. commercial_quality_ok = informational only. It does NOT mean the image needs
   the expensive fallback.

IMPORTANT POLICY FOR PASS/FAIL:
A hard fail should happen ONLY when there is a fundamental mismatch in one of:
- package/body shape
- visible lead/pin structure
- component/body color
- invented or removed physical features

Do NOT fail the candidate merely for:
- uncertain comparison
- marking mismatch
- marking uncertainty
- commercial polish not being ideal
- holes/tabs uncertainty unless already reflected as a shape mismatch

Keep issues short and visual-only. Do not expose hidden reasoning.
""".strip()

VALIDATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "package_geometry": {
            "type": "string",
            "enum": ["match", "mismatch", "uncertain"],
        },
        "lead_structure": {
            "type": "string",
            "enum": ["match", "mismatch", "uncertain", "not_applicable"],
        },
        "body_color_consistency": {
            "type": "string",
            "enum": ["match", "mismatch", "uncertain"],
        },
        "holes_tabs_features": {
            "type": "string",
            "enum": ["match", "mismatch", "uncertain", "not_applicable"],
        },
        "markings_consistency": {
            "type": "string",
            "enum": ["match", "mismatch", "uncertain"],
        },
        "invented_or_removed_features": {"type": "boolean"},
        "commercial_quality_ok": {"type": "boolean"},
        "identity_confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
    },
    "required": [
        "package_geometry",
        "lead_structure",
        "body_color_consistency",
        "holes_tabs_features",
        "markings_consistency",
        "invented_or_removed_features",
        "commercial_quality_ok",
        "identity_confidence",
        "issues",
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


def _deterministic_pass(obj: dict) -> tuple[bool, list[str]]:
    """Only structural mismatches can unlock the expensive fallback route."""
    reasons: list[str] = []

    if obj.get("invented_or_removed_features"):
        reasons.append("invented_or_removed_features")

    if obj.get("package_geometry") == "mismatch":
        reasons.append("package_geometry_mismatch")

    if obj.get("lead_structure") == "mismatch":
        reasons.append("lead_structure_mismatch")

    if obj.get("body_color_consistency") == "mismatch":
        reasons.append("body_color_mismatch")

    return not reasons, reasons


def validate(client: OpenAI, reference: Path, candidate: Path) -> dict:
    model = os.getenv("IDENTITY_VALIDATOR_MODEL", "gpt-5.4-nano-2026-03-17")
    detail = os.getenv("IDENTITY_VALIDATOR_IMAGE_DETAIL", "high")

    response = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": VALIDATOR_PROMPT + "\n\nIMAGE A — ORIGINAL REFERENCE:"},
                {"type": "input_image", "image_url": _data_url(reference), "detail": detail},
                {"type": "input_text", "text": "IMAGE B — REGENERATED CANDIDATE:"},
                {"type": "input_image", "image_url": _data_url(candidate), "detail": detail},
            ],
        }],
        text={
            "format": {
                "type": "json_schema",
                "name": "product_image_identity_validation",
                "strict": True,
                "schema": VALIDATOR_SCHEMA,
            }
        },
        max_output_tokens=450,
    )

    if response.status == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
        raise RuntimeError(f"Identity validator returned incomplete response: {reason}")

    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("Identity validator returned no structured output")

    obj = json.loads(text)
    passed, rejection_reasons = _deterministic_pass(obj)
    obj["pass"] = passed
    obj["rejection_reasons"] = rejection_reasons
    obj["_api_accounting"] = api_accounting_from_response(model, response)
    return obj
