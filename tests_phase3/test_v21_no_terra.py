from pathlib import Path
import json


def test_active_code_and_config_do_not_reference_terra():
    root = Path(__file__).resolve().parents[1]
    active = [
        root / "ocr.py",
        root / "preflight.py",
        root / "metadata_manager.py",
        root / "pipeline.py",
        root / "integrated_pipeline.py",
        root / "phase3_fact_extraction" / "pipeline.py",
        root / "phase3_fact_extraction" / "clients.py",
        root / "phase3_final" / "pipeline.py",
        root / "phase3_final" / "model_router.py",
        root / ".env.example",
    ]
    for path in active:
        text = path.read_text(encoding="utf-8").casefold()
        assert "terra" not in text, path
    cfg = json.loads((root / "config" / "phase3_final.json").read_text(encoding="utf-8"))
    assert "terra" not in json.dumps(cfg).casefold()
    assert cfg["pdf_max_calls_per_product"] == 1
    assert cfg["pdf_primary_model"] == "gpt-5.6-luna"
    assert cfg["cheap_writer_model"] == "gpt-5.6-luna"
    assert cfg["expensive_writer_max_attempts"] == 0


def test_ocr_is_luna_primary_sol_fallback():
    text = (Path(__file__).resolve().parents[1] / "ocr.py").read_text(encoding="utf-8")
    assert 'OCR_MODEL_PRIMARY", "gpt-5.6-luna"' in text
    assert 'OCR_MODEL_FALLBACK", "gpt-5.6-sol"' in text
