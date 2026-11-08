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


def test_phase4_publisher_uses_new_product_flow_and_phase3_content():
    import ast

    publisher_path = ROOT / "phase4" / "publisher.py"
    source = publisher_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    # Detect duplicated publisher tails/entrypoints introduced by file rewrites.
    definitions = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    ]
    assert len(definitions) == len(set(definitions))
    assert source.count('if __name__ == "__main__":') == 1
    publish_one = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "publish_one"
    )
    steps_assignment = next(
        node for node in publish_one.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "steps" for target in node.targets)
    )
    step_keys = [item.elts[0].value for item in steps_assignment.value.elts]
    assert step_keys == [
        "title_content", "image", "datasheet", "short_description",
        "snippet", "focus_keyword", "attributes", "sku", "category",
    ]

    assert 'title.fill(bundle.title)' in source
    assert 'set_editor_html(page, "content", bundle.html)' in source
    assert 'set_editor_html(page, "excerpt", bundle.short_description_html)' in source
    assert 'title.fill(bundle.seo_title)' in source
    assert 'description.fill(bundle.meta_description)' in source
    assert 'pn.casefold() not in seo_title.casefold()' in source
    save_draft = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "save_draft"
    )
    save_clicks = [
        node for node in ast.walk(save_draft)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "click"
    ]
    assert len(save_clicks) == 1  # no blind second Save Draft click
    assert 'store.duplicate_guard(pn)' in source
    assert 'locate_existing_wordpress_product(page, bundle)' in source
    assert 'wp_repair' not in source.lower()
    assert 'save_attributes.click' not in source.lower()
    assert 'page.locator("#publish")' not in source


def test_phase4_first_visible_nudges_scroll_before_final_locator_retry():
    from phase4.publisher import first_visible

    class FakeLocator:
        def __init__(self, page):
            self.page = page

        def count(self):
            return 1

        def nth(self, index):
            return self

        def is_visible(self):
            return self.page.target_visible

    class FakePage:
        def __init__(self):
            self.target_visible = False
            self.scroll_calls = 0

        def locator(self, selector):
            return FakeLocator(self)

        def evaluate(self, expression, arg=None):
            if "window.scrollY" in expression:
                return 0
            if "window.scrollBy" in expression:
                self.scroll_calls += 1
                self.target_visible = True
            return 0

        def wait_for_timeout(self, milliseconds):
            return None

    page = FakePage()
    locator = first_visible(page, ["#late-rendered-control"], timeout_ms=1)
    assert locator.is_visible()
    assert page.scroll_calls >= 2


def test_phase4_click_handler_gets_one_scroll_retry():
    from phase4.publisher import click_with_scroll_retry

    class FakeLocator:
        def __init__(self):
            self.click_count = 0

        def scroll_into_view_if_needed(self, timeout=None):
            return None

        def click(self, timeout=None):
            self.click_count += 1
            if self.click_count == 1:
                raise RuntimeError("simulated transient handler failure")

        def wait_for(self, state=None, timeout=None):
            return None

    class FakePage:
        def __init__(self):
            self.scroll_calls = 0

        def evaluate(self, expression, arg=None):
            if "window.scrollY" in expression:
                return 0
            if "window.scrollBy" in expression:
                self.scroll_calls += 1
            return 0

        def wait_for_timeout(self, milliseconds):
            return None

    page = FakePage()
    locator = FakeLocator()
    click_with_scroll_retry(page, locator, "test handler", timeout_ms=1)
    assert locator.click_count == 2
    assert page.scroll_calls >= 2


def test_phase4_category_check_works_without_explicit_scroll_method():
    """Playwright check() scrolls automatically; lightweight mocks need only check()."""
    from phase4.publisher import check_with_scroll_retry

    class Checkbox:
        def __init__(self):
            self.checked = False

        def check(self, timeout=None):
            self.checked = True

        def is_checked(self):
            return self.checked

    class NoScrollPage:
        def evaluate(self, *args, **kwargs):
            raise AssertionError("No manual scroll should run when check succeeds")

    checkbox = Checkbox()
    check_with_scroll_retry(NoScrollPage(), checkbox, "Select IGBT category")
    assert checkbox.checked


def test_phase4_category_check_scroll_retry_on_transient_failure(monkeypatch):
    from phase4 import publisher

    nudges = []

    class Checkbox:
        def __init__(self):
            self.calls = 0
            self.checked = False

        def check(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient checkbox handler failure")
            self.checked = True

        def is_checked(self):
            return self.checked

    monkeypatch.setattr(publisher, "scroll_nudge_down_up", lambda page, reason: nudges.append(reason))
    checkbox = Checkbox()
    publisher.check_with_scroll_retry(object(), checkbox, "Select exact category", timeout_ms=100)
    assert checkbox.checked
    assert checkbox.calls == 2
    assert nudges == ["Select exact category"]
