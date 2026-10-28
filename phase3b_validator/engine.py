import json
from pathlib import Path

from .hard_gates import part_number_integrity
from .metrics import build_metrics
from .scoring import score_metrics

_REQUIRED_TOP = ["schema_version", "identity", "content", "page", "snippet", "seo", "images", "links", "technical_safety", "source", "generation"]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def basic_validate(bundle: dict) -> None:
    missing = [k for k in _REQUIRED_TOP if k not in bundle]
    if missing:
        raise ValueError(f"Missing top-level fields: {', '.join(missing)}")
    if bundle.get("schema_version") != "phase3b-seo-bundle-v0.1":
        raise ValueError("Unsupported schema_version")
    if not bundle.get("identity", {}).get("part_number"):
        raise ValueError("identity.part_number is required")
    if not bundle.get("seo", {}).get("focus_keyword"):
        raise ValueError("seo.focus_keyword is required")
    content = bundle.get("content", {})
    if not content.get("body_markdown") and not content.get("markdown_path"):
        raise ValueError("content.body_markdown is required (legacy markdown_path also accepted)")


def resolve_relative(base_json: Path, maybe_path: str) -> Path:
    p = Path(maybe_path)
    return p if p.is_absolute() else (base_json.parent / p).resolve()


def analyze_bundle(bundle_path, config_path=None) -> dict:
    bundle_path = Path(bundle_path).resolve()
    root = Path(__file__).resolve().parents[1]
    if config_path is None:
        config_path = root / "config" / "rankmath_reference_product_v0.1.json"
    cfg = load_json(Path(config_path))
    bundle = load_json(bundle_path)
    basic_validate(bundle)

    content = bundle.get("content", {})
    if content.get("body_markdown"):
        md = str(content["body_markdown"])
    else:
        md_path = resolve_relative(bundle_path, content["markdown_path"])
        if not md_path.exists():
            raise FileNotFoundError(f"Markdown not found: {md_path}")
        md = md_path.read_text(encoding="utf-8")

    metrics = build_metrics(bundle, md, cfg.get("site_domain", "tavakolelectronic.com"))
    scoring = score_metrics(metrics, cfg)
    hidden_gate = part_number_integrity(bundle, md)

    return {
        "product": bundle["identity"]["part_number"],
        "product_title": bundle["page"].get("product_title", ""),
        "score": scoring["score"],
        # retained internally for tests/calibration; CLI V0.1 does not print these
        "_metrics": metrics,
        "_scoring": scoring,
        "_hard_gates": {"part_number_integrity": hidden_gate},
        "_profile": cfg["profile"],
    }
