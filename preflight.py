from pathlib import Path
import os
from dotenv import load_dotenv
from orchestrator.api_coordinator import CoordinatedOpenAI as OpenAI


REQUIRED_DIRS = [
    "input", "input_PN", "PN_input", "output", "Final", "metadata", "assets", "datasheets",
    "seo", "logs", "ready_for_upload", "audit_history",
]
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


def _quality(name: str, default: str):
    value = os.getenv(name, default).strip().lower()
    if value not in {"low", "medium", "high", "auto"}:
        raise RuntimeError(f"{name} must be one of: low, medium, high, auto")
    return value


def _detail(name: str, default: str = "high"):
    value = os.getenv(name, default).strip().lower()
    if value not in {"low", "high", "auto"}:
        raise RuntimeError(f"{name} must be one of: low, high, auto")
    return value


def _positive_int(name: str, default: str):
    value = int(os.getenv(name, default))
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def run_preflight(root: Path):
    load_dotenv(root / ".env")

    missing = [directory for directory in REQUIRED_DIRS if not (root / directory).is_dir()]
    if missing:
        raise RuntimeError("Missing required directories: " + ", ".join(missing))

    logo = root / "assets" / "store_logo.png"
    if not logo.is_file():
        raise RuntimeError("Missing assets/store_logo.png")

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing. Copy .env.example to .env and add the key.")

    _quality("REGENERATION_PRIMARY_QUALITY", "low")
    _quality("REGENERATION_FALLBACK_QUALITY", "medium")

    min_kb = _positive_int("MIN_KB", "50")
    max_kb = _positive_int("MAX_KB", "100")
    if min_kb > max_kb:
        raise RuntimeError("MIN_KB/MAX_KB configuration is invalid")

    safe_w = _positive_int("SAFE_ZONE_WIDTH", "330")
    safe_h = _positive_int("SAFE_ZONE_HEIGHT", "330")
    logo_w = _positive_int("LOGO_MAX_WIDTH", "260")
    logo_h = _positive_int("LOGO_MAX_HEIGHT", "260")
    margin = int(os.getenv("LOGO_MARGIN", "40"))
    if margin < 0:
        raise RuntimeError("LOGO_MARGIN must be zero or positive")
    if margin + logo_w > safe_w or margin + logo_h > safe_h:
        raise RuntimeError(
            "Logo dimensions/margin can exceed the configured safe zone; "
            "increase SAFE_ZONE_WIDTH/HEIGHT or reduce logo size/margin"
        )

    prompt_level = int(os.getenv("REGENERATION_MAX_PROMPT_LEVEL", "1"))
    if prompt_level < 0 or prompt_level > 2:
        raise RuntimeError("REGENERATION_MAX_PROMPT_LEVEL must be 0, 1, or 2")

    _detail("PRECHECK_IMAGE_DETAIL", "high")
    _detail("IDENTITY_VALIDATOR_IMAGE_DETAIL", "high")

    precheck_threshold = float(os.getenv("PRECHECK_MIN_CONFIDENCE", "0.80"))
    if not 0.0 <= precheck_threshold <= 1.0:
        raise RuntimeError("PRECHECK_MIN_CONFIDENCE must be between 0 and 1")

    canvas_upscale = float(os.getenv("CANVAS_MAX_UPSCALE", "1.15"))
    if canvas_upscale <= 0:
        raise RuntimeError("CANVAS_MAX_UPSCALE must be greater than 0")

    safe_occ = float(os.getenv("SAFE_ZONE_MAX_OCCUPANCY", "0.012"))
    if not 0.0 <= safe_occ <= 1.0:
        raise RuntimeError("SAFE_ZONE_MAX_OCCUPANCY must be between 0 and 1")

    for name, default in (
        ("PRECHECK_MODEL", "gpt-5.4-nano-2026-03-17"),
        ("REGENERATION_MODEL", "gpt-image-2-2026-04-21"),
        ("REGENERATION_PRIMARY_MODEL", os.getenv("REGENERATION_MODEL", "gpt-image-2-2026-04-21")),
        ("REGENERATION_FALLBACK_MODEL", os.getenv("REGENERATION_MODEL", "gpt-image-2-2026-04-21")),
        ("IDENTITY_VALIDATOR_MODEL", "gpt-5.4-nano-2026-03-17"),
        ("OCR_MODEL_PRIMARY", "gpt-5.6-luna"),
        ("OCR_MODEL_FALLBACK", "gpt-5.6-sol"),
    ):
        if not os.getenv(name, default).strip():
            raise RuntimeError(f"{name} must not be empty")

    client = OpenAI(api_key=key)
    try:
        client.models.list()
    except Exception as exc:
        raise RuntimeError(f"OpenAI API connection failed: {exc}") from exc

    return client


def find_images(root: Path):
    return sorted(
        path for path in (root / "input").iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED
    )
