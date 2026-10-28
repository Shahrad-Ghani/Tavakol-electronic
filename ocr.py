from pathlib import Path
import base64
import io
import json
import os
import tempfile
from typing import Any

from PIL import Image, ImageChops, ImageOps, ImageStat
from openai import OpenAI

from api_accounting import from_response as api_accounting_from_response


OCR_PROMPT_VERSION = "v4.0-dual-image-cropped-fallback-ocr"

OCR_SCHEMA = {
    "type": "object",
    "properties": {
        "PartNumber": {"type": ["string", "null"]},
        "manufacturer": {"type": ["string", "null"]},
        "country": {"type": ["string", "null"]},
        "visible_lines_original": {"type": "array", "items": {"type": "string"}},
        "visible_lines_regenerated": {"type": "array", "items": {"type": "string"}},
        "visible_lines": {"type": "array", "items": {"type": "string"}},
        "primary_code": {"type": ["string", "null"]},
        "part_number_segments": {"type": "array", "items": {"type": "string"}},
        "part_number_layout": {"enum": ["single_line", "multi_line", "uncertain", None]},
        "part_number_confidence": {"enum": ["high", "medium", "low", "unreadable"]},
        "image_source_decision": {
            "enum": ["agreement", "original_dominant", "regenerated_aid", "uncertain"],
        },
        "secondary_codes": {"type": "array", "items": {"type": "string"}},
        "comparison_conflicts": {"type": "array", "items": {"type": "string"}},
        "candidate_part_numbers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": ["string", "null"]},
                    "confidence": {"type": ["number", "null"]},
                    "reason": {"type": ["string", "null"]},
                },
                "required": ["value", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
        "selected_candidate_reason": {"type": ["string", "null"]},
        "critical_character_review": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": ["string", "null"]},
    },
    "required": [
        "PartNumber",
        "manufacturer",
        "country",
        "visible_lines_original",
        "visible_lines_regenerated",
        "visible_lines",
        "primary_code",
        "part_number_segments",
        "part_number_layout",
        "part_number_confidence",
        "image_source_decision",
        "secondary_codes",
        "comparison_conflicts",
        "candidate_part_numbers",
        "selected_candidate_reason",
        "critical_character_review",
        "notes",
    ],
    "additionalProperties": False,
}


def _clean_list(values):
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def _clean_candidates(values):
    cleaned = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip() or None
        conf = item.get("confidence")
        try:
            conf = None if conf is None else float(conf)
        except Exception:
            conf = None
        reason = str(item.get("reason") or "").strip() or None
        cleaned.append({"value": value, "confidence": conf, "reason": reason})
    return cleaned


def _score(result: dict[str, Any]) -> int:
    rank = {"unreadable": 0, "low": 1, "medium": 2, "high": 3}
    return rank.get(str(result.get("part_number_confidence") or "unreadable").lower(), 0)


def _bbox_from_background(image: Image.Image):
    rgb = image.convert("RGB")
    w, h = rgb.size
    sample_margin_x = max(2, int(w * 0.04))
    sample_margin_y = max(2, int(h * 0.04))
    border = Image.new("RGB", (w, h), (255, 255, 255))

    # Estimate background from border strips.
    strips = []
    strips.append(rgb.crop((0, 0, w, sample_margin_y)))
    strips.append(rgb.crop((0, h - sample_margin_y, w, h)))
    strips.append(rgb.crop((0, 0, sample_margin_x, h)))
    strips.append(rgb.crop((w - sample_margin_x, 0, w, h)))
    pixels = []
    for strip in strips:
        stat = ImageStat.Stat(strip)
        vals = tuple(int(v) for v in stat.mean[:3])
        pixels.append(vals)
    bg = tuple(int(sum(x[i] for x in pixels) / len(pixels)) for i in range(3))
    border.paste(bg, (0, 0, w, h))

    diff = ImageChops.difference(rgb, border).convert("L")
    # Slight auto-contrast improves bbox detection on gray phone backgrounds.
    diff = ImageOps.autocontrast(diff)
    mask = diff.point(lambda p: 255 if p > 18 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return (0, 0, w, h)
    return bbox


def _pad_bbox(bbox, size, pad_ratio=0.08):
    left, top, right, bottom = bbox
    w, h = size
    bw = right - left
    bh = bottom - top
    px = max(8, int(bw * pad_ratio))
    py = max(8, int(bh * pad_ratio))
    return (
        max(0, left - px),
        max(0, top - py),
        min(w, right + px),
        min(h, bottom + py),
    )


def _marking_bbox(component_size):
    w, h = component_size
    # Conservative inner window emphasizing the central marking area.
    return (
        int(w * 0.18),
        int(h * 0.12),
        int(w * 0.82),
        int(h * 0.78),
    )


def _compose_ocr_view(path: Path) -> bytes:
    """Create a deterministic montage: top=tight component crop, bottom=enlarged marking crop."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        bbox = _pad_bbox(_bbox_from_background(im), im.size)
        comp = im.crop(bbox)

        mark = comp.crop(_marking_bbox(comp.size))

        top_w = 1100
        comp = ImageOps.contain(comp, (top_w, 780), method=Image.Resampling.LANCZOS)
        # Enlarge marking region aggressively for OCR.
        mark = ImageOps.contain(mark, (top_w, 900), method=Image.Resampling.LANCZOS)

        gap = 24
        out_w = max(comp.width, mark.width)
        bg = Image.new("RGB", (out_w, comp.height + gap + mark.height), (255, 255, 255))

        comp_x = (out_w - comp.width) // 2
        mark_x = (out_w - mark.width) // 2
        bg.paste(comp, (comp_x, 0))
        bg.paste(mark, (mark_x, comp.height + gap))

        # Final upscaling preserves small text detail for OCR.
        bg = bg.resize((bg.width * 2, bg.height * 2), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        bg.save(buf, format="PNG")
        return buf.getvalue()


def _data_url_from_bytes(data: bytes, mime: str = "image/png"):
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _build_prompt() -> str:
    return r"""
You are performing STRICT high-stakes OCR for an electronic-component identity pipeline.
Your output directly controls exact datasheet search, so a wrong Part Number is worse than returning null.

You receive TWO prepared images of the SAME physical component:
- IMAGE A = ORIGINAL PHONE PHOTO DERIVATIVE VIEW. This is the authority for characters.
- IMAGE B = REGENERATED/CLEANED IMAGE DERIVATIVE VIEW. This is a readability aid only.
Each prepared image contains:
  - a tight crop of the component on the TOP
  - an enlarged crop of the central marking area on the BOTTOM
Use both sections of each image.

ABSOLUTE RULES:
1. Prefer IMAGE A when A and B disagree on a readable character.
2. Use IMAGE B only to clarify weak/unreadable characters in A.
3. Never let B overwrite a clearly readable character from A.
4. Never use outside product knowledge, web knowledge, or remembered datasheets.
5. If the exact commercial Part Number is not sufficiently supported, return PartNumber=null.
6. Wrong exact OCR must be blocked rather than guessed.

MANDATORY METHOD:
- Read IMAGE A independently and list visible lines top-to-bottom.
- Read IMAGE B independently and list visible lines top-to-bottom.
- Reconcile them into authoritative visible_lines.
- Determine whether the Part Number is single-line or physically split across adjacent lines.
- Produce up to 3 candidate Part Numbers, then choose the best supported one.
- Explicitly review confusing characters before finalizing.

VERY IMPORTANT FREQUENT CONFUSIONS TO RE-CHECK:
B↔8, O↔0, I↔1, l↔1, S↔5, Z↔2, G↔6, C↔G, D↔0/O, U↔V, T↔7, Q↔0/O,
missing or invented hyphen '-', slash '/' vs '1', plus '+' vs '4'.
Do NOT resolve these by assumption. Re-check them visually, especially in IMAGE A.

SEGMENTATION RULES:
- Do NOT automatically drop a short prefix line above a longer alphanumeric line.
- Do NOT automatically concatenate every short prefix either.
- Decide based on alignment, typography, spacing, and the physical marking block.
- A real Part Number may span adjacent lines.
- Preserve characters exactly as supported; do not invent or remove characters.

EXAMPLES:
- TBA / 800 / COZB  -> may be TBA800 if the first two lines visibly form the identifier.
- TB / 6560AFTG / 242GA+1 / JAPAN -> may be TB6560AFTG if TB and 6560AFTG visibly form one identifier.
  Carefully re-check B versus 8 in the prefix.
- TB / 8800HG / 2220GB1 -> do NOT automatically produce TB8800HG. Only do so if the marking structure supports it.

MANUFACTURER / COUNTRY:
- manufacturer is only a visible marking observation from these images, not canonical identity.
- country is only a visible marking observation like JAPAN, MALAYSIA, etc.
- If not visually established, return null.

OUTPUT RULES:
- primary_code must equal the chosen PartNumber or null.
- If part_number_confidence is low or unreadable, then PartNumber MUST be null and primary_code MUST be null.
- candidate_part_numbers should contain up to 3 candidates sorted best-first.
- selected_candidate_reason should explain why the final candidate was chosen.
- critical_character_review should list concrete decisions such as "IMAGE A supports B, not 8".
- comparison_conflicts should record important A-vs-B disagreements.

CONFIDENCE:
- high: exact characters and segmentation are clearly supported.
- medium: exact code is supported but one image is weak and the other helps.
- low: unresolved uncertainty remains.
- unreadable: no reliable commercial code can be extracted.

FAIL-SAFE:
If there is unresolved ambiguity in the actual Part Number, prefer returning PartNumber=null.
""".strip()


def _single_pass(client: OpenAI, model: str, original_bytes: bytes, regenerated_bytes: bytes):
    response = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": _build_prompt()},
                {"type": "input_text", "text": "IMAGE A — ORIGINAL PHONE PHOTO DERIVATIVE VIEW — CHARACTER AUTHORITY"},
                {"type": "input_image", "image_url": _data_url_from_bytes(original_bytes), "detail": "original"},
                {"type": "input_text", "text": "IMAGE B — REGENERATED/CLEANED DERIVATIVE VIEW — READABILITY AID ONLY"},
                {"type": "input_image", "image_url": _data_url_from_bytes(regenerated_bytes), "detail": "original"},
            ],
        }],
        reasoning={"effort": os.getenv("OCR_REASONING_EFFORT", "medium")},
        text={
            "format": {
                "type": "json_schema",
                "name": "component_markings_dual_image_ocr",
                "strict": True,
                "schema": OCR_SCHEMA,
            }
        },
        max_output_tokens=1200,
    )
    if response.status == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
        raise RuntimeError(f"OCR returned incomplete response: {reason}")
    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("OCR returned no structured output")
    obj = json.loads(text)
    return obj, response


def _normalize_result(obj: dict[str, Any], model_used: str, response, models_tried: list[str], fallback_used: bool, ocr_view_mode: str):
    visible_original = _clean_list(obj.get("visible_lines_original"))
    visible_regenerated = _clean_list(obj.get("visible_lines_regenerated"))
    visible_lines = _clean_list(obj.get("visible_lines"))
    secondary_codes = _clean_list(obj.get("secondary_codes"))
    segments = _clean_list(obj.get("part_number_segments"))
    conflicts = _clean_list(obj.get("comparison_conflicts"))
    char_review = _clean_list(obj.get("critical_character_review"))
    candidates = _clean_candidates(obj.get("candidate_part_numbers"))[:3]

    primary_code = str(obj.get("primary_code") or "").strip() or None
    part_number = str(obj.get("PartNumber") or "").strip() or None
    confidence = str(obj.get("part_number_confidence") or "unreadable").strip().lower()
    notes = obj.get("notes")

    # Defensive gate: Phase 2 must never receive a low-confidence OCR identity.
    if confidence not in {"high", "medium"}:
        if part_number or primary_code:
            gate_note = f"PartNumber blocked because part_number_confidence={confidence}."
            notes = gate_note if not notes else f"{notes} {gate_note}"
        part_number = None
        primary_code = None

    # Strict internal consistency.
    if part_number and primary_code and part_number != primary_code:
        conflict_note = (
            f"PartNumber blocked because structured output disagreed: "
            f"PartNumber={part_number!r}, primary_code={primary_code!r}."
        )
        conflicts.append(conflict_note)
        notes = conflict_note if not notes else f"{notes} {conflict_note}"
        part_number = None
        primary_code = None
        confidence = "low"

    if part_number and not primary_code:
        primary_code = part_number
    elif primary_code and not part_number and confidence in {"high", "medium"}:
        part_number = primary_code

    secondary_codes = [code for code in secondary_codes if code != part_number]

    return {
        "PartNumber": part_number,
        "manufacturer": obj.get("manufacturer"),
        "country": obj.get("country"),
        "visible_lines_original": visible_original,
        "visible_lines_regenerated": visible_regenerated,
        "visible_lines": visible_lines,
        "primary_code": primary_code,
        "part_number_segments": segments,
        "part_number_layout": obj.get("part_number_layout"),
        "part_number_confidence": confidence,
        "image_source_decision": obj.get("image_source_decision"),
        "secondary_codes": secondary_codes,
        "comparison_conflicts": conflicts,
        "critical_character_review": char_review,
        "candidate_part_numbers": candidates,
        "selected_candidate_reason": obj.get("selected_candidate_reason"),
        "notes": notes,
        "_api_accounting": api_accounting_from_response(model_used, response),
        "_model_used": model_used,
        "_models_tried": models_tried,
        "_fallback_used": fallback_used,
        "_ocr_view_mode": ocr_view_mode,
    }


def _needs_fallback(result: dict[str, Any]) -> bool:
    if not result.get("PartNumber"):
        return True
    if result.get("part_number_confidence") != "high":
        return True
    if result.get("image_source_decision") == "uncertain":
        return True
    if result.get("part_number_layout") == "uncertain":
        return True
    if result.get("comparison_conflicts"):
        return True
    return False


def _combine_results(primary: dict[str, Any], fallback: dict[str, Any]):
    ps = _score(primary)
    fs = _score(fallback)

    if fallback.get("PartNumber") and not primary.get("PartNumber"):
        return fallback
    if primary.get("PartNumber") and not fallback.get("PartNumber"):
        return primary

    if primary.get("PartNumber") and fallback.get("PartNumber"):
        if primary["PartNumber"] == fallback["PartNumber"]:
            return fallback if fs >= ps else primary
        # Model disagreement on acceptable-looking outputs => block rather than guess.
        blocked = fallback if fs >= ps else primary
        conflicts = list(blocked.get("comparison_conflicts") or [])
        conflicts.append(
            f"Primary and fallback OCR models disagreed: primary={primary.get('PartNumber')!r}, fallback={fallback.get('PartNumber')!r}."
        )
        blocked = dict(blocked)
        blocked["comparison_conflicts"] = conflicts
        blocked["notes"] = (
            (blocked.get("notes") or "") + " OCR blocked because primary and fallback models disagreed on the exact PartNumber."
        ).strip()
        blocked["PartNumber"] = None
        blocked["primary_code"] = None
        blocked["part_number_confidence"] = "low"
        return blocked

    # Both failed; keep the stronger signal if any.
    return fallback if fs >= ps else primary


def extract(client: OpenAI, original_image: Path, regenerated_image: Path | None = None):
    """Dual-image OCR with deterministic crop/upscale and model fallback.

    - OCR PRIMARY: GPT-5.6 Luna (default)
    - OCR FALLBACK: GPT-5.6 Sol (default) only when primary remains uncertain.
    - Both original and regenerated images are converted into deterministic OCR views
      with a tight component crop plus enlarged marking crop.
    """
    regenerated_image = regenerated_image or original_image

    original_bytes = _compose_ocr_view(original_image)
    regenerated_bytes = _compose_ocr_view(regenerated_image)

    primary_model = os.getenv("OCR_MODEL_PRIMARY", "gpt-5.6-luna")
    fallback_model = os.getenv("OCR_MODEL_FALLBACK", "gpt-5.6-sol")

    obj1, resp1 = _single_pass(client, primary_model, original_bytes, regenerated_bytes)
    result1 = _normalize_result(
        obj1,
        model_used=primary_model,
        response=resp1,
        models_tried=[primary_model],
        fallback_used=False,
        ocr_view_mode="dual-image-cropped-upscaled",
    )

    if not _needs_fallback(result1):
        return result1

    if not fallback_model or fallback_model == primary_model:
        return result1

    obj2, resp2 = _single_pass(client, fallback_model, original_bytes, regenerated_bytes)
    result2 = _normalize_result(
        obj2,
        model_used=fallback_model,
        response=resp2,
        models_tried=[primary_model, fallback_model],
        fallback_used=True,
        ocr_view_mode="dual-image-cropped-upscaled",
    )
    return _combine_results(result1, result2)
