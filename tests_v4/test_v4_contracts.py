from pathlib import Path
import json

from core.category_registry import category_context, load_registry, product_slug, product_title
from core.package_resolution import clean_package
from phase3_final.seo_snippet_agent import DeterministicSeoSnippetAgent

ROOT = Path(__file__).resolve().parents[1]


def test_category_registry_contains_all_v4_children_and_real_diodes_url():
    reg = load_registry()
    assert reg["schema_version"] == "1.0"
    assert len(reg["categories"]) == 26
    diode = reg["categories"]["diode"]
    assert diode["wordpress"]["term_id"] == 111
    assert diode["wordpress"]["parent_term_id"] == 110
    assert diode["category_url"] == "https://tavakolelectronic.com/product-category/قطعات-الکترونیکی/دیود/"


def test_category_aware_title_density_slug_and_wordpress_mapping():
    ctx = category_context("mosfet")
    assert product_title("IRF3205", "mosfet") == "ماسفت IRF3205"
    assert ctx["density_phrase"] == "این ماسفت"
    assert product_slug("IRF3205", "mosfet") == "irf3205-mosfet"
    assert ctx["wordpress"]["term_id"] == 115
    assert ctx["wordpress"]["parent_term_id"] == 110


def test_independent_seo_agent_mock_is_category_aware_and_pn_once_in_title():
    agent = DeterministicSeoSnippetAgent()
    out, api = agent.generate(part_number="IRF3205", category_key="mosfet", manufacturer=None, safe_facts=[])
    assert "ماسفت" in out["seo_title"]
    assert out["seo_title"].count("IRF3205") == 1
    assert "IRF3205" in out["meta_description"]
    repeated, _ = agent.generate(part_number="IRF3205", category_key="mosfet", manufacturer=None, safe_facts=[])
    other, _ = agent.generate(part_number="2N7000", category_key="mosfet", manufacturer=None, safe_facts=[])
    assert repeated == out
    assert other["seo_title"] != out["seo_title"]
    assert api["provider"] == "local-mock"


def test_package_cleaner_never_keeps_narrative_sentence():
    assert clean_package("The device is available in a 24-pin SDIP package") in {"SDIP", "24-pin SDIP", "SDIP24"}
    assert clean_package("This device is supplied in a package intended for many applications and environments") is None


def test_rank_math_and_short_description_contract_present_in_publisher_source():
    text = (ROOT / "phase4" / "publisher.py").read_text(encoding="utf-8")
    assert "rank-math-editor-title" in text
    assert "rank-math-editor-permalink" in text
    assert "rank-math-editor-description" in text
    assert "set_short_description" in text
    assert "Save Draft" in text or "save draft" in text.lower()


def test_v4_registry_urls_are_https_and_have_term_ids():
    cats = load_registry()["categories"]
    for key, rec in cats.items():
        assert rec["category_url"].startswith("https://tavakolelectronic.com/product-category/"), key
        assert isinstance(rec["wordpress"]["term_id"], int), key
        assert isinstance(rec["wordpress"]["parent_term_id"], int), key


def test_v4_manual_input_folder_is_canonical_and_legacy_is_only_fallback(tmp_path):
    from admin_audit import find_pn_input_images
    from PIL import Image
    legacy = tmp_path / "PN_input"
    legacy.mkdir()
    Image.new("RGB", (8, 8), "white").save(legacy / "LEGACY123.png")
    # Without V4 folder, legacy tree is accepted for migration/backward compatibility.
    assert [p.name for p in find_pn_input_images(tmp_path)] == ["LEGACY123.png"]
    canonical = tmp_path / "input_PN"
    canonical.mkdir()
    Image.new("RGB", (8, 8), "white").save(canonical / "V4PN123.png")
    # Once canonical V4 folder exists, Manual mode only sees input_PN/.
    assert [p.name for p in find_pn_input_images(tmp_path)] == ["V4PN123.png"]



def test_batch_category_is_only_a_default_for_new_metadata(tmp_path):
    from metadata_manager import load_or_create, save
    from core.metadata_v3 import get_category_key

    meta, data = load_or_create(tmp_path, "NEW_IGBT_001", category="igbt_transistor")
    assert get_category_key(data) == "igbt_transistor"

    data["part_number"] = "NEW_IGBT_001"
    save(meta, data)

    _, resumed = load_or_create(tmp_path, "NEW_IGBT_001", category="mosfet")
    assert get_category_key(resumed) == "igbt_transistor"


def test_manual_pn_input_category_is_creation_only(tmp_path):
    from PIL import Image
    from admin_audit import prepare_pn_input_metadata
    from core.metadata_v3 import get_category_key

    input_dir = tmp_path / "input_PN"
    input_dir.mkdir(parents=True)
    image_path = input_dir / "IGBT_MANUAL_001.png"
    Image.new("RGB", (24, 24), "white").save(image_path)

    meta, first = prepare_pn_input_metadata(tmp_path, image_path, category_key="igbt_transistor")
    assert get_category_key(first) == "igbt_transistor"

    _, resumed = prepare_pn_input_metadata(tmp_path, image_path, category_key="mosfet")
    assert get_category_key(resumed) == "igbt_transistor"
    assert resumed["product_title"] == product_title("IGBT_MANUAL_001", "igbt_transistor")
