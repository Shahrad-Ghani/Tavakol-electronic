from pathlib import Path
import base64
import os
import time
import tempfile
from PIL import Image
from openai import OpenAI
from api_accounting import from_response as api_accounting_from_response


PROMPT_VERSION = "v5.0-economy-first-reference-lock"
PROMPT_LEVEL_NAMES = {
    0: "primary-economy",
    1: "fallback-structural-correction",
    2: "fallback-maximum-fidelity-optional",
}

MASTER_PROMPT = r"""
Task: Edit the provided reference image into a clean ecommerce-ready product image of the same single electronic component.

This is a conservative product-photo regeneration task.
The reference image is the only authority for the component’s physical identity.
Do not redesign, reinterpret, normalize, restore unseen structure, or replace the component.

Main goal:
Make the component look cleaner, sharper, better lit, and more suitable for a professional ecommerce website,
while preserving the exact visible identity of the photographed object.

Priority order:
1. Preserve exact visible physical identity
2. Preserve exact visible package shape, visible feature presence/absence, and visible lead/pin structure
3. Preserve exact visible body color / dominant material color impression
4. Preserve visible markings and logo positions without guessing missing characters
5. Improve photographic cleanliness and product-photo presentation
6. Use a clean pure-white background

Reference-first rules:
- Treat the reference image as documentary evidence of one real physical object.
- Generate only that object, not a typical example of the product family.
- If the reference is imperfect, asymmetric, worn, old, noisy, or visually unusual, preserve the object identity anyway.

Identity lock:
- Preserve the exact package/body outline and proportions.
- Preserve the exact orientation and viewing angle.
- Preserve all visible holes, notches, tabs, recesses, cutouts, exposed metal, corners, and structural details.
- Preserve the exact visible pin/lead/terminal count, placement, spacing, direction, length, bends, and attachment points.
- Preserve the dominant body color and visible metal color impression. Do not recolor the component into a meaningfully different object.
- Preserve visible printed markings in the same locations. Do not retype, autocorrect, invent, expand, or complete text.

Critical evidence rule:
- Only depict what is visibly supported by the reference image.
- If a feature is not clearly visible, do not add it.
- If a feature is ambiguous, preserve the ambiguity instead of guessing.
- Absence in the reference is authoritative.

Allowed improvements:
- cleaner isolation from the background
- cleaner edges
- improved sharpness and micro-contrast
- better tonal separation
- slightly improved readability of already-visible markings through lighting/contrast only
- more realistic and cleaner material rendering
- more even exposure
- reduced visual noise
- subtle professional ecommerce product-photo polish

Forbidden changes:
- feature invention
- feature removal
- package redesign
- geometry correction
- pin invention
- pin removal
- lead straightening that changes visible structure
- symmetry correction
- replacing irregular structure with a cleaner standard version
- recoloring the component into a noticeably different body color
- text retyping or text completion
- dramatic cinematic styling
- dramatic reflections or shadows
- glossy advertising-render look
- any extra object, logo, watermark, or graphic

Composition requirements:
- Use a pure white background.
- Show only the single component.
- Keep the full component visible and uncropped.
- Do not try to reserve logo space in the image. External software will handle final layout and logo placement.

Desired style:
A subtle premium ecommerce product-photo look.
Improve cleanliness and quality, but remain obviously the same physical component.

Behavior under uncertainty:
If there is any conflict between beautification and fidelity, choose fidelity.
If you are uncertain, stay closer to the reference instead of making a more idealized image.
""".strip()

PINLESS_ADDENDUM = r"""
Pinless / no-visible-leads addendum:
This reference image shows zero clearly visible external pins/leads/terminals.
This absence is authoritative.
The output must also show zero clearly visible external pins/leads/terminals.
Do not add hidden or typical package pins. Do not convert the part into a leaded IC.
""".strip()

IRREGULAR_ADDENDUM = r"""
Irregular-geometry addendum:
This component has mechanically unusual visible geometry.
Preserve all unusual visible geometry exactly.
Do not simplify, regularize, center, balance, or standardize it.
""".strip()

COMMERCIAL_POLISH_ADDENDUM = r"""
Commercial polish addendum:
The result should feel cleaner and more professional than the raw reference photo,
but it must still look like the same photographed object rather than a different or idealized component.
""".strip()

RETRY_1_PROMPT = r"""
Fallback retry — strict structural correction mode.

The previous cheaper attempt introduced an unacceptable identity change.
Correct it by matching the reference more literally and more conservatively.

Hard correction targets:
- restore the correct package/body shape
- restore the correct visible lead/pin count and arrangement
- restore the correct dominant component/body color impression
- remove any invented or removed physical feature

Important:
- Do not use a typical package template.
- Do not normalize geometry.
- Do not add missing-looking pins.
- Do not recolor the component.
- Do not guess unclear markings.

Still keep the result usable for ecommerce:
clean white background, clean edges, realistic rendering, better clarity, better lighting,
and subtle commercial polish — but only after structural fidelity is restored.
""".strip()

RETRY_2_PROMPT = r"""
Optional second fallback — maximum reference fidelity.

Stay extremely close to the reference and minimize generative freedom.
Only improve background cleanliness, edge clarity, sharpness, and lighting balance.
Any doubt must be resolved in favor of the reference image, not an idealized component.
""".strip()


def _precheck_addendums(precheck: dict | None) -> list[str]:
    selected = list((precheck or {}).get("selected_addendums") or [])
    if "commercial_polish" not in selected:
        selected.append("commercial_polish")
    return selected


def build_prompt(prompt_level: int = 0, precheck: dict | None = None) -> str:
    level = max(0, min(int(prompt_level), 2))
    selected = _precheck_addendums(precheck)
    sections = [MASTER_PROMPT]
    if "pinless" in selected:
        sections.append(PINLESS_ADDENDUM)
    if "irregular" in selected:
        sections.append(IRREGULAR_ADDENDUM)
    sections.append(COMMERCIAL_POLISH_ADDENDUM)
    if level >= 1:
        sections.append(RETRY_1_PROMPT)
    if level >= 2:
        sections.append(RETRY_2_PROMPT)
    return "\n\n---\n\n".join(sections)


def prompt_addendum_names(precheck: dict | None = None) -> list[str]:
    return _precheck_addendums(precheck)


def prompt_name(prompt_level: int = 0) -> str:
    level = max(0, min(int(prompt_level), 2))
    return PROMPT_LEVEL_NAMES[level]


def select_route(precheck: dict | None = None, prompt_level: int = 0) -> dict:
    """V1.5 is economy-first.

    Every image starts on the cheap GPT Image 2 / low route.
    Only a structural mismatch in the validator can escalate the image to the
    more expensive GPT Image 2 / medium fallback route.
    """
    level = max(0, min(int(prompt_level), 2))
    base_model = os.getenv("REGENERATION_MODEL", "gpt-image-2-2026-04-21")

    if level >= 1:
        return {
            "model": os.getenv("REGENERATION_FALLBACK_MODEL", base_model),
            "quality": os.getenv("REGENERATION_FALLBACK_QUALITY", "medium"),
            "route": "strict-fallback",
            "risk_tier": "fallback",
        }

    return {
        "model": os.getenv("REGENERATION_PRIMARY_MODEL", base_model),
        "quality": os.getenv("REGENERATION_PRIMARY_QUALITY", "low"),
        "route": "economy-first-primary",
        "risk_tier": "economy_first",
    }


def _edit_kwargs(model: str, image_file, prompt: str, quality: str):
    kwargs = {
        "model": model,
        "image": image_file,
        "prompt": prompt,
        "size": os.getenv("REGENERATION_SIZE", "1024x1024"),
        "quality": quality,
        "background": "opaque",
    }
    if model in {"gpt-image-1.5", "gpt-image-1"}:
        kwargs["input_fidelity"] = "high"
    return kwargs


def regenerate(
    client: OpenAI,
    source: Path,
    output: Path,
    prompt_level: int = 0,
    precheck: dict | None = None,
    api_retries: int | None = None,
    route: dict | None = None,
):
    if api_retries is None:
        api_retries = int(os.getenv("REGENERATION_API_RETRIES", "2"))
    api_retries = max(1, api_retries)

    prompt = build_prompt(prompt_level, precheck=precheck)
    route = dict(route or select_route(precheck, prompt_level))
    model = route["model"]
    quality = route["quality"]
    last_error = None

    for api_attempt in range(1, api_retries + 1):
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="altimate_image_input_") as scratch:
                upload = source
                # Some WebP uploads are sent with application/octet-stream by
                # the SDK/server. PNG gives an unambiguous supported MIME type.
                if source.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                    upload = Path(scratch) / "reference.png"
                    with Image.open(source) as image:
                        image.convert("RGB").save(upload, format="PNG")
                with open(upload, "rb") as image_file:
                    result = client.images.edit(**_edit_kwargs(model, image_file, prompt, quality))
            b64 = result.data[0].b64_json
            if not b64:
                raise RuntimeError("Image API returned no b64_json payload")
            output.write_bytes(base64.b64decode(b64))
            return {
                "api_attempts": api_attempt,
                "model": model,
                "quality": quality,
                "route": route.get("route"),
                "risk_tier": route.get("risk_tier"),
                "api_accounting": api_accounting_from_response(model, result),
            }
        except Exception as exc:
            last_error = exc
            if api_attempt < api_retries:
                time.sleep(min(2 ** (api_attempt - 1), 4))

    raise RuntimeError(str(last_error))
