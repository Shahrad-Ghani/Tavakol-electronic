# Merge status — Phase 1 + Phase 2 + Phase 3 Integrated V1.0

No manual code merge is required. The runtime entry point is `run_ui.py` or `run_integrated.py`.

Key integration points:

- `pipeline.py::process_one(..., on_part_number_ready=...)` emits the canonical PN immediately after OCR/metadata rename.
- `orchestrator.engine.IntegratedOrchestrator` queues that item to Phase 2 immediately; it does not wait for a 10-item micro-batch.
- `phase2.resolver_v43.extract_mouser_package()` extracts physical `Package / Case` only from Mouser `ProductAttributes`; top-level sales `Packaging` is ignored.
- `metadata_manager.save()` is the Phase-1/canonical merge-safe writer.
- `metadata_manager.save_phase2()` patches only Phase-2-owned fields onto the newest canonical record so concurrent P1/P2 writes cannot overwrite each other.
- A terminal Phase-2 datasheet decision immediately queues Phase 3.
- Phase 3 remains Altimate V1.2 at the prompt/model/fact-boundary level.
- Phase 3 runtime does not create content `.md` files; `body_markdown` remains inside JSON/memory and HTML is written directly.
- `products/PART_NUMBER.json` is emitted only after P1+P2 metadata, Phase3 product and integrated JSON schemas all validate.
- `run_ui.py` provides separate Phase 1 / Phase 2 / Phase 3 live log panes.
- Internet/service outages auto-wait and resume from checkpoint; API auth/credit errors stop the current run without deleting progress.
