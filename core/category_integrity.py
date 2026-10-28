from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.category_registry import category_context, normalize_category_key, product_slug, product_title


class CategoryConsistencyError(ValueError):
    """Raised when one product carries conflicting category identities."""


@dataclass(frozen=True)
class CategoryIntegrityResult:
    key: str
    expected_title: str
    expected_slug: str


def _norm_required(value: Any, *, source: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise CategoryConsistencyError(f"CATEGORY_CONSISTENCY_ERROR: {source} is missing")
    key = normalize_category_key(raw)
    if not key:
        raise CategoryConsistencyError(
            f"CATEGORY_CONSISTENCY_ERROR: {source} has unknown category value {raw!r}"
        )
    return key


def metadata_category_key(meta: dict[str, Any]) -> str:
    """Return the immutable run category from canonical metadata without IC fallback."""
    block = meta.get("category") if isinstance(meta.get("category"), dict) else {}
    block_raw = block.get("key")
    product_type_raw = meta.get("product_type")
    block_key = _norm_required(block_raw, source="metadata.category.key")
    product_type_key = _norm_required(product_type_raw, source="metadata.product_type")
    if block_key != product_type_key:
        raise CategoryConsistencyError(
            "CATEGORY_CONSISTENCY_ERROR: metadata category disagreement "
            f"category.key={block_key!r} product_type={product_type_key!r}"
        )
    return block_key


def phase3_category_key(p3: dict[str, Any], *, legacy_ic_fallback: bool = False) -> str:
    identity = p3.get("identity") if isinstance(p3.get("identity"), dict) else {}
    raw = identity.get("product_category")
    if not str(raw or "").strip() and legacy_ic_fallback:
        return "ic"
    return _norm_required(raw, source="phase3.identity.product_category")


def integrated_category_key(integrated: dict[str, Any], *, legacy_ic_fallback: bool = False) -> str:
    identity = integrated.get("identity") if isinstance(integrated.get("identity"), dict) else {}
    raw = identity.get("category")
    if not str(raw or "").strip() and legacy_ic_fallback:
        return "ic"
    key = _norm_required(raw, source="integrated.identity.category")
    ctx = identity.get("category_context") if isinstance(identity.get("category_context"), dict) else {}
    ctx_raw = ctx.get("key")
    if not str(ctx_raw or "").strip() and legacy_ic_fallback:
        return key
    ctx_key = _norm_required(ctx_raw, source="integrated.identity.category_context.key")
    if key != ctx_key:
        raise CategoryConsistencyError(
            "CATEGORY_CONSISTENCY_ERROR: integrated category disagreement "
            f"identity.category={key!r} category_context.key={ctx_key!r}"
        )
    return key


def _assert_equal(expected: str, actual: str, source: str) -> None:
    if expected != actual:
        raise CategoryConsistencyError(
            f"CATEGORY_CONSISTENCY_ERROR: expected category={expected!r} but {source}={actual!r}"
        )


def assert_upstream_category_consistency(
    meta: dict[str, Any],
    *,
    phase3: dict[str, Any] | None = None,
    integrated: dict[str, Any] | None = None,
) -> CategoryIntegrityResult:
    """Enforce one immutable category across Metadata -> Phase3 -> Integrated Product.

    This intentionally does not silently repair conflicts. Category is selected by the
    user at run start and later stages are consumers of that decision.
    """
    key = metadata_category_key(meta)
    pn = str(meta.get("part_number") or meta.get("PartNumber") or "").strip()
    if not pn:
        raise CategoryConsistencyError("CATEGORY_CONSISTENCY_ERROR: metadata part_number is missing")
    expected_title = product_title(pn, key)
    expected_slug = product_slug(pn, key)

    metadata_title = str(meta.get("product_title") or "").strip()
    if metadata_title and metadata_title != expected_title:
        raise CategoryConsistencyError(
            "CATEGORY_CONSISTENCY_ERROR: metadata product_title does not match category; "
            f"expected={expected_title!r} got={metadata_title!r}"
        )

    if phase3 is not None:
        p3_pn = str((phase3.get("identity") or {}).get("part_number") or "").strip()
        if p3_pn and p3_pn.casefold() != pn.casefold():
            raise CategoryConsistencyError(
                f"CATEGORY_CONSISTENCY_ERROR: phase3 part_number={p3_pn!r} metadata part_number={pn!r}"
            )
        identity = phase3.get("identity") if isinstance(phase3.get("identity"), dict) else {}
        policy = phase3.get("internal_link_policy") if isinstance(phase3.get("internal_link_policy"), dict) else {}
        legacy_ic = key == "ic" and not str(identity.get("product_category") or "").strip()
        p3_key = phase3_category_key(phase3, legacy_ic_fallback=legacy_ic)
        _assert_equal(key, p3_key, "phase3.identity.product_category")
        page = phase3.get("page") if isinstance(phase3.get("page"), dict) else {}
        p3_title = str(page.get("product_title") or "").strip()
        p3_slug = str(page.get("slug") or "").strip()
        # Legacy IC fixtures/runs predate V4 category-aware slug/link policy.
        # Non-IC products and any record carrying the V4 policy are strict.
        strict_derived_fields = key != "ic" or bool(policy.get("policy_key"))
        if strict_derived_fields and p3_title and p3_title != expected_title:
            raise CategoryConsistencyError(
                "CATEGORY_CONSISTENCY_ERROR: phase3 product_title does not match category; "
                f"expected={expected_title!r} got={p3_title!r}"
            )
        if strict_derived_fields and p3_slug and p3_slug != expected_slug:
            raise CategoryConsistencyError(
                "CATEGORY_CONSISTENCY_ERROR: phase3 slug does not match category; "
                f"expected={expected_slug!r} got={p3_slug!r}"
            )
        if policy:
            policy_key = _norm_required(policy.get("policy_key"), source="phase3.internal_link_policy.policy_key")
            _assert_equal(key, policy_key, "phase3.internal_link_policy.policy_key")
            expected_url = str(category_context(key).get("category_url") or "").strip()
            target_url = str(policy.get("target_url") or "").strip()
            if target_url and target_url.rstrip("/") != expected_url.rstrip("/"):
                raise CategoryConsistencyError(
                    "CATEGORY_CONSISTENCY_ERROR: phase3 internal category link does not match registry; "
                    f"expected={expected_url!r} got={target_url!r}"
                )

    if integrated is not None:
        i_pn = str((integrated.get("identity") or {}).get("part_number") or "").strip()
        if i_pn and i_pn.casefold() != pn.casefold():
            raise CategoryConsistencyError(
                f"CATEGORY_CONSISTENCY_ERROR: integrated part_number={i_pn!r} metadata part_number={pn!r}"
            )
        i_identity = integrated.get("identity") if isinstance(integrated.get("identity"), dict) else {}
        legacy_ic = key == "ic" and not str(i_identity.get("category") or "").strip()
        i_key = integrated_category_key(integrated, legacy_ic_fallback=legacy_ic)
        _assert_equal(key, i_key, "integrated.identity.category")
        preview = integrated.get("publishing_preview") if isinstance(integrated.get("publishing_preview"), dict) else {}
        i_title = str(preview.get("product_title") or "").strip()
        i_slug = str(preview.get("slug") or "").strip()
        strict_derived_fields = not legacy_ic
        if strict_derived_fields and i_title and i_title != expected_title:
            raise CategoryConsistencyError(
                "CATEGORY_CONSISTENCY_ERROR: integrated publishing title does not match category; "
                f"expected={expected_title!r} got={i_title!r}"
            )
        if strict_derived_fields and i_slug and i_slug != expected_slug:
            raise CategoryConsistencyError(
                "CATEGORY_CONSISTENCY_ERROR: integrated publishing slug does not match category; "
                f"expected={expected_slug!r} got={i_slug!r}"
            )

    return CategoryIntegrityResult(key=key, expected_title=expected_title, expected_slug=expected_slug)


def assert_bundle_category_consistency(
    product: dict[str, Any],
    *,
    expected_key: str | None = None,
) -> CategoryIntegrityResult:
    """Validate a ready_for_upload/product.json against the central registry."""
    pn = str(product.get("part_number") or "").strip()
    if not pn:
        raise CategoryConsistencyError("CATEGORY_CONSISTENCY_ERROR: bundle part_number is missing")

    product_type = _norm_required(product.get("product_type"), source="bundle.product_type")
    block = product.get("category") if isinstance(product.get("category"), dict) else {}
    block_key = _norm_required(block.get("key"), source="bundle.category.key")
    wp = product.get("wordpress") if isinstance(product.get("wordpress"), dict) else {}
    wp_key = _norm_required(wp.get("category_key"), source="bundle.wordpress.category_key")

    if product_type != block_key or product_type != wp_key:
        raise CategoryConsistencyError(
            "CATEGORY_CONSISTENCY_ERROR: bundle category disagreement "
            f"product_type={product_type!r} category.key={block_key!r} wordpress.category_key={wp_key!r}"
        )
    if expected_key is not None:
        expected = _norm_required(expected_key, source="expected category")
        _assert_equal(expected, product_type, "bundle.product_type")
        key = expected
    else:
        key = product_type

    ctx = category_context(key)
    expected_title = product_title(pn, key)
    expected_slug = product_slug(pn, key)
    title = str(product.get("product_title") or "").strip()
    slug = str((product.get("seo") or {}).get("permalink") or "").strip()
    if title != expected_title:
        raise CategoryConsistencyError(
            f"CATEGORY_CONSISTENCY_ERROR: bundle title expected={expected_title!r} got={title!r}"
        )
    if slug != expected_slug:
        raise CategoryConsistencyError(
            f"CATEGORY_CONSISTENCY_ERROR: bundle slug expected={expected_slug!r} got={slug!r}"
        )

    expected_wp = ctx["wordpress"]
    category = wp.get("category") if isinstance(wp.get("category"), dict) else {}
    checks = {
        "bundle.wordpress.category.parent": (str(category.get("parent") or "").strip(), str(expected_wp["parent"]).strip()),
        "bundle.wordpress.category.child": (str(category.get("child") or "").strip(), str(expected_wp["child"]).strip()),
        "bundle.wordpress.category_parent_term_id": (str(wp.get("category_parent_term_id") or ""), str(expected_wp["parent_term_id"])),
        "bundle.wordpress.category_term_id": (str(wp.get("category_term_id") if wp.get("category_term_id") is not None else ""), str(expected_wp["term_id"])),
    }
    for source, (actual, expected) in checks.items():
        if actual != expected:
            raise CategoryConsistencyError(
                f"CATEGORY_CONSISTENCY_ERROR: {source} expected={expected!r} got={actual!r}"
            )

    return CategoryIntegrityResult(key=key, expected_title=expected_title, expected_slug=expected_slug)
