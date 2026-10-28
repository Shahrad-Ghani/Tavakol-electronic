import json
from pathlib import Path

import pytest

from bundles import canonical_bundle as cb
from core.category_integrity import (
    CategoryConsistencyError,
    assert_bundle_category_consistency,
    assert_upstream_category_consistency,
)
from core.category_registry import category_context
from metadata_manager import _new_record, rename_metadata_to_partnumber


def _meta(pn="2N7000", key="mosfet"):
    m = _new_record(pn, key)
    m["part_number"] = pn
    m["product_title"] = f"ماسفت {pn}" if key == "mosfet" else f"آی سی {pn}"
    m["category"] = category_context(key)
    m["product_type"] = key
    m["admin_audit"]["status"] = "APPROVED"
    m["admin_audit"]["classification"] = "FINALIZED"
    m["publishing"]["bundle_status"] = "READY"
    return m


def _p3(pn="2N7000", key="mosfet"):
    ctx = category_context(key)
    return {
        "identity": {"part_number": pn, "product_category": key},
        "page": {"product_title": f"{ctx['title_prefix']} {pn}", "slug": f"{pn.lower()}-{key}"},
        "internal_link_policy": {"policy_key": key, "target_url": ctx["category_url"]},
    }


def _integrated(pn="2N7000", key="mosfet"):
    ctx = category_context(key)
    return {
        "identity": {"part_number": pn, "category": key, "category_context": ctx},
        "publishing_preview": {"product_title": f"{ctx['title_prefix']} {pn}", "slug": f"{pn.lower()}-{key}"},
    }


def test_category_is_immutable_across_metadata_phase3_and_integrated():
    result = assert_upstream_category_consistency(_meta(), phase3=_p3(), integrated=_integrated())
    assert result.key == "mosfet"
    assert result.expected_title == "ماسفت 2N7000"
    assert result.expected_slug == "2n7000-mosfet"


def test_category_mismatch_is_hard_error_not_ic_fallback():
    with pytest.raises(CategoryConsistencyError, match="CATEGORY_CONSISTENCY_ERROR"):
        assert_upstream_category_consistency(_meta(), phase3=_p3(key="ic"), integrated=_integrated())


def test_bundle_category_registry_mapping_is_strict():
    ctx = category_context("mosfet")
    product = {
        "part_number": "2N7000",
        "product_type": "mosfet",
        "category": ctx,
        "product_title": "ماسفت 2N7000",
        "seo": {"permalink": "2n7000-mosfet"},
        "wordpress": {
            "category_key": "mosfet",
            "category": {"parent": ctx["wordpress"]["parent"], "child": ctx["wordpress"]["child"]},
            "category_parent_term_id": ctx["wordpress"]["parent_term_id"],
            "category_term_id": ctx["wordpress"]["term_id"],
        },
    }
    assert assert_bundle_category_consistency(product, expected_key="mosfet").key == "mosfet"
    product["product_type"] = "ic"
    with pytest.raises(CategoryConsistencyError):
        assert_bundle_category_consistency(product, expected_key="mosfet")


def test_rename_metadata_title_uses_selected_category(tmp_path):
    root = tmp_path
    (root / "metadata").mkdir()
    current = root / "metadata" / "source.json"
    data = _meta()
    current.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = rename_metadata_to_partnumber(root, current, data)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["product_title"] == "ماسفت 2N7000"
    assert saved["category"]["key"] == "mosfet"


def test_existing_wrong_ic_bundle_is_archived_and_rebuilt(tmp_path, monkeypatch):
    root = tmp_path
    for d in ("metadata", "phase3_outputs", "products", "ready_for_upload"):
        (root / d).mkdir(parents=True, exist_ok=True)
    meta = _meta()
    meta_path = root / "metadata" / "2N7000.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "phase3_outputs" / "2N7000.json").write_text(json.dumps(_p3(), ensure_ascii=False), encoding="utf-8")
    (root / "products" / "2N7000.json").write_text(json.dumps(_integrated(), ensure_ascii=False), encoding="utf-8")

    stale = root / "ready_for_upload" / "2N7000"
    stale.mkdir()
    stale_product = {
        "part_number": "2N7000",
        "product_type": "ic",
        "category": category_context("ic"),
        "wordpress": {"category_key": "ic"},
    }
    (stale / "product.json").write_text(json.dumps(stale_product, ensure_ascii=False), encoding="utf-8")

    rebuilt = []
    def fake_build(root_arg, meta_path_arg, data_arg=None):
        dest = Path(root_arg) / "ready_for_upload" / "2N7000"
        dest.mkdir(parents=True, exist_ok=True)
        ctx = category_context("mosfet")
        product = {
            "part_number": "2N7000", "product_type": "mosfet", "category": ctx,
            "product_title": "ماسفت 2N7000", "seo": {"permalink": "2n7000-mosfet"},
            "wordpress": {
                "category_key": "mosfet",
                "category": {"parent": ctx["wordpress"]["parent"], "child": ctx["wordpress"]["child"]},
                "category_parent_term_id": ctx["wordpress"]["parent_term_id"],
                "category_term_id": ctx["wordpress"]["term_id"],
            },
        }
        (dest / "product.json").write_text(json.dumps(product, ensure_ascii=False), encoding="utf-8")
        rebuilt.append("2N7000")
        return dest
    monkeypatch.setattr(cb, "build_canonical_bundle", fake_build)

    result = cb.prepare_approved_bundles(root)
    assert result["rebuilt"] == ["2N7000"]
    assert result["built"] == ["2N7000"]
    assert rebuilt == ["2N7000"]
    assert list((root / "audit_history" / "stale_category_bundles").iterdir())
