# Catalog Automation Agent — Integrated V4.0.2 Patch

## Production issue fixed
A recovery run on V4 produced:

`Integrated product schema validation failed at identity.category_context: 'key' is a required property`

Root cause was twofold:
1. `metadata_manager._canonicalize_before_write()` still removed the V4 canonical `category` block as if it were a legacy alias.
2. `orchestrator.adapter.build_integrated_product()` copied `meta["category"]` directly into `identity.category_context`. Old/current metadata could therefore provide `{}` even though `product_type=mosfet` was present.

## Fix
- Preserve the canonical `category` block during metadata writes.
- Build `identity.category_context` from the central Category Registry using `get_category_key(meta)`.
- Keep strict schema validation enabled. No `additionalProperties=true` relaxation was introduced.

## Compatibility
- Existing metadata that lost its `category` block remains recoverable because `product_type` is used to resolve the canonical category key.
- New metadata persists the full canonical Category Context.
- V4.0.1 Fact Safety package and targeted repair fixes are retained.

## Validation
- Full offline/mock pytest suite passed.
- No live OpenAI, Mouser, or WordPress calls were made.
