import json
from pathlib import Path


def test_compat_key_exists_but_expensive_tier_is_disabled_and_not_terra():
    cfg=json.loads(Path("config/phase3_final.json").read_text(encoding="utf-8"))
    assert cfg["expensive_writer_model"] == "gpt-5.6-luna"
    assert cfg["expensive_writer_max_attempts"] == 0
    assert cfg["pdf_fallback_model"] == "gpt-5.6-luna"
    assert cfg["expensive_escalation_below_score"] == 0
    assert "terra" not in json.dumps(cfg).casefold()


def test_active_pipeline_does_not_construct_expensive_agent():
    text=Path("phase3_final/pipeline.py").read_text(encoding="utf-8")
    assert "self.expensive_agent = None" in text
    assert "gpt-5.6-terra" not in text
