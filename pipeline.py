from pathlib import Path
import os
import traceback
from datetime import datetime
from dotenv import load_dotenv

from preflight import run_preflight, find_images
from metadata_manager import (
    load_or_create,
    save,
    save_phase2,
    utc_now,
    rename_metadata_to_partnumber,
    portable_path,
    resolve_recorded_path,
)
from regenerator import (
    regenerate,
    PROMPT_VERSION,
    prompt_name,
    prompt_addendum_names,
    select_route,
)
from precheck import analyze as run_visual_precheck, derive_routing as derive_precheck_routing, PRECHECK_PROMPT_VERSION
from identity_validator import (
    validate as run_identity_validation,
    IDENTITY_VALIDATOR_PROMPT_VERSION,
)
from ocr import extract, OCR_PROMPT_VERSION
from image_optimizer import fit_to_canvas, optimize_final
from logo_overlay import overlay_logo
from safe_zone import safe_zone_ok
from api_accounting import record_stage as record_api_stage
from phase2 import Phase2Coordinator, Phase2Pipeline
from phase2.metadata_state import MetadataStore
from core.metadata_v3 import stage_completed, image_finalized, deterministic_product_title


ROOT = Path(__file__).resolve().parent
_PHASE1_LOG_SINK = None


def set_phase1_log_sink(callback):
    global _PHASE1_LOG_SINK
    _PHASE1_LOG_SINK = callback


def log(message, log_file=None):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {message}"
    print(line)
    if _PHASE1_LOG_SINK:
        try:
            _PHASE1_LOG_SINK(message)
        except Exception:
            pass
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_phase2_coordinator(log_file: Path):
    if not _env_flag("PHASE2_ENABLED", True):
        log("[PHASE2] disabled by PHASE2_ENABLED=0", log_file)
        return None
    api_key = os.getenv("MOUSER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("PHASE2_ENABLED=1 but MOUSER_API_KEY is missing from .env")
    proxy_name = os.getenv("PHASE2_PROXY_FILE", "proxies.txt").strip() or "proxies.txt"
    proxy_file = ROOT / proxy_name
    if not proxy_file.exists():
        raise RuntimeError(f"PHASE2 proxy file not found: {proxy_file}")

    store = MetadataStore(ROOT, save_callback=save_phase2)
    phase2_pipeline = Phase2Pipeline(
        project_root=ROOT,
        metadata_dir=ROOT / "metadata",
        datasheet_dir=ROOT / "datasheets",
        proxy_file=proxy_file,
        api_key=api_key,
        debug_dir=ROOT / "debug_html",
        metadata_store=store,
        retry_not_found=_env_flag("PHASE2_RETRY_NOT_FOUND", False),
        retry_manual=_env_flag("PHASE2_RETRY_MANUAL", False),
    )
    log("[PHASE2] coordinator ready | Mouser micro-batch max=10 | global wait target=NONE", log_file)
    return Phase2Coordinator(phase2_pipeline)


def _phase2_enqueue(coordinator, meta_path: Path, ref: str, log_file: Path):
    if coordinator is None:
        return
    try:
        processed = coordinator.enqueue(meta_path)
        log(f"[PHASE2-QUEUE] {ref} | metadata={meta_path.name} | processed_now={processed}", log_file)
    except Exception as exc:
        # Phase 2 failure is recorded/logged without corrupting Phase 1 product state.
        log(f"[PHASE2-ERROR] {ref} | enqueue/process | {type(exc).__name__}: {exc}", log_file)


def _safe_zone_settings():
    return (
        int(os.getenv("SAFE_ZONE_WIDTH", "330")),
        int(os.getenv("SAFE_ZONE_HEIGHT", "330")),
        float(os.getenv("SAFE_ZONE_MAX_OCCUPANCY", "0.012")),
    )


def _max_prompt_level() -> int:
    return max(0, min(int(os.getenv("REGENERATION_MAX_PROMPT_LEVEL", "1")), 2))


def _logo_zone_clear(data: dict) -> bool:
    history = (data.get("regeneration") or {}).get("attempt_history") or []
    if history:
        return bool(history[-1].get("logo_zone_clear"))
    return False


def _highest_attempted_prompt_level(data: dict) -> int:
    levels = []
    current = data.get("regeneration", {}).get("prompt_level")
    if current is not None:
        try:
            levels.append(int(current))
        except Exception:
            pass
    for item in data.get("regeneration", {}).get("attempt_history", []) or []:
        try:
            levels.append(int(item.get("prompt_level", 0) or 0))
        except Exception:
            continue
    return max(levels) if levels else 0


def _locate_working_image(ref: str, data) -> Path | None:
    candidates = [
        ROOT / "output" / f"{ref}_regen.png",
        ROOT / "output" / f"{ref}.png",
    ]
    if not stage_completed(data.get("logo")):
            return next((p for p in candidates if p.exists()), None)


def _record_validation(data: dict, result: dict, model: str, candidate: Path, prompt_level: int):
    record = {
        "pass": bool(result.get("pass")),
        "model": model,
        "prompt_version": IDENTITY_VALIDATOR_PROMPT_VERSION,
        "candidate": portable_path(ROOT, candidate),
        "prompt_level": prompt_level,
        "package_geometry": result.get("package_geometry"),
        "lead_structure": result.get("lead_structure"),
        "body_color_consistency": result.get("body_color_consistency"),
        "holes_tabs_features": result.get("holes_tabs_features"),
        "markings_consistency": result.get("markings_consistency"),
        "invented_or_removed_features": result.get("invented_or_removed_features"),
        "commercial_quality_ok": result.get("commercial_quality_ok"),
        "identity_confidence": result.get("identity_confidence"),
        "issues": result.get("issues") or [],
        "rejection_reasons": result.get("rejection_reasons") or [],
        "completed_at": utc_now(),
    }
    history = data["identity_validation"].setdefault("history", [])
    history.append(record)
    data["identity_validation"].update({
        "status": "completed" if record["pass"] else "rejected",
        "model": model,
        "prompt_version": IDENTITY_VALIDATOR_PROMPT_VERSION,
        "pass": record["pass"],
        "package_geometry": record["package_geometry"],
        "lead_structure": record["lead_structure"],
        "body_color_consistency": record["body_color_consistency"],
        "holes_tabs_features": record["holes_tabs_features"],
        "markings_consistency": record["markings_consistency"],
        "invented_or_removed_features": record["invented_or_removed_features"],
        "commercial_quality_ok": record["commercial_quality_ok"],
        "identity_confidence": record["identity_confidence"],
        "issues": record["issues"],
        "rejection_reasons": record["rejection_reasons"],
        "last_error": None,
        "completed_at": record["completed_at"],
    })
    return record


def _append_regen_history(data: dict, entry: dict):
    data["regeneration"].setdefault("attempt_history", []).append(entry)


def _generate_until_approved(client, source: Path, ref: str, meta_path: Path, data, log_file: Path, start_level=0):
    working = ROOT / "output" / f"{ref}_regen.png"
    canvas = ROOT / "output" / f"{ref}_canvas.png"
    max_level = _max_prompt_level()
    start_level = max(0, min(int(start_level), max_level))
    width, height, max_occupancy = _safe_zone_settings()
    precheck_data = data.get("precheck", {})
    prompt_profile = precheck_data.get("prompt_profile") or "standard"
    prompt_addendums = prompt_addendum_names(precheck_data)
    validator_model = os.getenv("IDENTITY_VALIDATOR_MODEL", "gpt-5.4-nano-2026-03-17")

    for level in range(start_level, max_level + 1):
        level_name = prompt_name(level)
        route = select_route(precheck_data, level)
        model = route["model"]
        quality = route["quality"]
        route_name = route["route"]

        log(
            f"[RUN] {ref} | regeneration | route={route_name} | model={model} | quality={quality} | "
            f"prompt={PROMPT_VERSION} | profile={prompt_profile} | addendums={','.join(prompt_addendums)} | "
            f"level={level}:{level_name}",
            log_file,
        )

        data["regeneration"].update({
            "status": "running",
            "model": model,
            "quality": quality,
            "route": route_name,
            "routing_mode": "economy-first-cheap-then-structural-fallback-v1",
            "prompt_version": PROMPT_VERSION,
            "prompt_level": level,
            "prompt_profile": prompt_profile,
            "prompt_addendums": prompt_addendums,
            "last_error": None,
        })
        save(meta_path, data)

        attempt_started = utc_now()
        try:
            regen_result = regenerate(
                client,
                source,
                working,
                prompt_level=level,
                precheck=precheck_data,
                route=route,
            )
            record_api_stage(data, "regeneration", regen_result.get("api_accounting"))
            data["regeneration"]["attempts"] = data["regeneration"].get("attempts", 0) + 1
            log(
                f"[OK] {ref} | regeneration candidate | route={route_name} | quality={quality} | "
                f"level={level} | api_attempts={regen_result['api_attempts']} | file={working.name}",
                log_file,
            )
        except Exception as exc:
            data["regeneration"].update({"status": "failed", "last_error": str(exc)})
            save(meta_path, data)
            log(f"[FAIL] {ref} | regeneration | level={level} | {exc}", log_file)
            return None, None

        log(f"[RUN] {ref} | canvas layout | target=1254x1254 | deterministic-logo-space | level={level}", log_file)
        try:
            fit_to_canvas(working, canvas)
            safe_ok, occupancy = safe_zone_ok(canvas, width, height, max_occupancy)
            log(
                f"[OK] {ref} | canvas layout | size=1254x1254 | logo_zone_clear={safe_ok} | occupancy={occupancy:.2%} | level={level}",
                log_file,
            )
        except Exception as exc:
            data["regeneration"].update({"status": "failed", "last_error": str(exc)})
            save(meta_path, data)
            log(f"[FAIL] {ref} | canvas layout | {exc}", log_file)
            return None, None

        history_entry = {
            "attempt": data["regeneration"]["attempts"],
            "prompt_level": level,
            "prompt_name": level_name,
            "route": route_name,
            "model": model,
            "quality": quality,
            "api_attempts": regen_result["api_attempts"],
            "logo_zone_clear": bool(safe_ok),
            "logo_zone_occupancy": round(float(occupancy), 6),
            "identity_validation_pass": None,
            "started_at": attempt_started,
            "completed_at": utc_now(),
        }

        log(
            f"[RUN] {ref} | identity validation | model={validator_model} | prompt={IDENTITY_VALIDATOR_PROMPT_VERSION} | level={level}",
            log_file,
        )
        data["identity_validation"].update({
            "status": "running",
            "model": validator_model,
            "prompt_version": IDENTITY_VALIDATOR_PROMPT_VERSION,
            "last_error": None,
        })
        save(meta_path, data)
        try:
            validation = run_identity_validation(client, source, canvas)
            record_api_stage(data, "identity_validation", validation.get("_api_accounting"))
            record = _record_validation(data, validation, validator_model, canvas, level)
        except Exception as exc:
            data["identity_validation"].update({
                "status": "failed",
                "last_error": str(exc),
                "completed_at": None,
            })
            _append_regen_history(data, history_entry)
            save(meta_path, data)
            log(f"[FAIL] {ref} | identity validation | {exc}", log_file)
            return None, None

        history_entry["identity_validation_pass"] = record["pass"]
        history_entry["identity_confidence"] = record["identity_confidence"]
        history_entry["validation_rejection_reasons"] = record["rejection_reasons"]
        history_entry["completed_at"] = utc_now()
        _append_regen_history(data, history_entry)

        if record["pass"]:
            data["regeneration"].update({
                "status": "completed",
                "last_error": None,
                "completed_at": utc_now(),
                "prompt_level": level,
                "model": model,
                "quality": quality,
                "route": route_name,
            })
            save(meta_path, data)
            log(
                f"[OK] {ref} | identity validation | pass=true | confidence={record['identity_confidence']} | "
                f"fallback_reasons=none",
                log_file,
            )
            return working, canvas

        reasons = ",".join(record["rejection_reasons"]) or "validator_rejected"
        data["regeneration"].update({
            "status": "retry_required",
            "last_error": f"Structural mismatch rejected candidate: {reasons}",
            "prompt_level": level,
            "completed_at": None,
        })
        save(meta_path, data)

        if level < max_level:
            log(
                f"[RETRY] {ref} | identity validation | structural_reasons={reasons} | "
                f"next=medium+{level + 1}:{prompt_name(level + 1)}",
                log_file,
            )
            continue

        log(
            f"[BLOCK] {ref} | identity validation | structural_reasons={reasons} | maximum prompt level exhausted",
            log_file,
        )
        return None, None

    return None, None


def _validate_existing_candidate(client, source: Path, canvas: Path, ref: str, meta_path: Path, data, log_file: Path):
    validator_model = os.getenv("IDENTITY_VALIDATOR_MODEL", "gpt-5.4-nano-2026-03-17")
    log(f"[RUN] {ref} | identity validation | existing candidate | model={validator_model}", log_file)
    try:
        result = run_identity_validation(client, source, canvas)
        record_api_stage(data, "identity_validation", result.get("_api_accounting"))
        record = _record_validation(
            data,
            result,
            validator_model,
            canvas,
            int(data.get("regeneration", {}).get("prompt_level", 0) or 0),
        )
        save(meta_path, data)
        if record["pass"]:
            log(
                f"[OK] {ref} | identity validation | existing candidate accepted | confidence={record['identity_confidence']}",
                log_file,
            )
            return True
        log(
            f"[RETRY] {ref} | identity validation | existing candidate structurally rejected | reasons={','.join(record['rejection_reasons'])}",
            log_file,
        )
        return False
    except Exception as exc:
        data["identity_validation"].update({"status": "failed", "last_error": str(exc)})
        save(meta_path, data)
        log(f"[FAIL] {ref} | identity validation | existing candidate | {exc}", log_file)
        return None


def process_one(client, source: Path, log_file: Path, phase2_coordinator=None, on_part_number_ready=None):
    ref = source.stem
    meta_path, data = load_or_create(ROOT, ref)

    log(f"[START] {ref} | source={source.name}", log_file)

    if data.get("part_number"):
        try:
            old_meta = meta_path
            meta_path = rename_metadata_to_partnumber(ROOT, meta_path, data)
            if old_meta.resolve() != meta_path.resolve():
                log(f"[OK] {ref} | metadata rename | {old_meta.name} -> {meta_path.name}", log_file)
        except Exception as exc:
            log(f"[FAIL] {ref} | metadata rename | {exc}", log_file)
            return

    if image_finalized(data):
        log(
            f"[SKIP] {ref} | finalization | already completed | final={data.get('image_optimization', {}).get('file')}",
            log_file,
        )
        log(f"[FINALIZED] {ref} | PartNumber={data.get('part_number')} | metadata={meta_path.name}", log_file)
        if on_part_number_ready and data.get("part_number"):
            on_part_number_ready(meta_path, data, ref)
        else:
            _phase2_enqueue(phase2_coordinator, meta_path, ref, log_file)
        return

    if not stage_completed(data.get("precheck")):
        precheck_model = os.getenv("PRECHECK_MODEL", "gpt-5.4-nano-2026-03-17")
        log(
            f"[RUN] {ref} | precheck | model={precheck_model} | prompt={PRECHECK_PROMPT_VERSION}",
            log_file,
        )
        data["precheck"].update({
            "status": "running",
            "model": precheck_model,
            "prompt_version": PRECHECK_PROMPT_VERSION,
            "last_error": None,
        })
        save(meta_path, data)
        try:
            result = run_visual_precheck(client, source)
            record_api_stage(data, "precheck", result.get("_api_accounting"))
            for key in (
                "visible_leads_state",
                "visible_lead_count",
                "lead_state_confidence",
                "irregular_geometry",
                "irregular_features",
                "irregular_confidence",
                "selected_addendums",
                "prompt_profile",
                "high_risk",
                "risk_tier",
                "risk_reasons",
                "regeneration_route",
                "recommended_regeneration_model",
                "recommended_regeneration_quality",
                "notes",
            ):
                data["precheck"][key] = result.get(key)
            data["precheck"].update({
                "status": "completed",
                "model": precheck_model,
                "prompt_version": PRECHECK_PROMPT_VERSION,
                "last_error": None,
                "completed_at": utc_now(),
            })
            save(meta_path, data)
            log(
                f"[OK] {ref} | precheck | leads={data['precheck']['visible_leads_state']} | "
                f"lead_count={data['precheck']['visible_lead_count']} | irregular={data['precheck']['irregular_geometry']} | "
                f"route={data['precheck']['regeneration_route']} | model={data['precheck']['recommended_regeneration_model']} | "
                f"quality={data['precheck']['recommended_regeneration_quality']} | profile={data['precheck']['prompt_profile']} | "
                f"addendums={','.join(data['precheck']['selected_addendums'])}",
                log_file,
            )
        except Exception as exc:
            data["precheck"].update({"status": "failed", "last_error": str(exc), "completed_at": None})
            save(meta_path, data)
            log(f"[FAIL] {ref} | precheck | {exc}", log_file)
            return
    else:
        if not data.get("precheck", {}).get("regeneration_route"):
            routed = derive_precheck_routing(data.get("precheck", {}))
            data["precheck"].update(routed)
            save(meta_path, data)
            log(
                f"[OK] {ref} | precheck route migration | route={data['precheck']['regeneration_route']} | "
                f"model={data['precheck']['recommended_regeneration_model']} | quality={data['precheck']['recommended_regeneration_quality']}",
                log_file,
            )
        log(
            f"[SKIP] {ref} | precheck | status.precheck=true | profile={data.get('precheck', {}).get('prompt_profile')} | "
            f"route={data.get('precheck', {}).get('regeneration_route')}",
            log_file,
        )

    working = ROOT / "output" / f"{ref}_regen.png"
    canvas = ROOT / "output" / f"{ref}_canvas.png"

    if not stage_completed(data.get("regeneration")):
        previous_state = data.get("regeneration", {}).get("status")
        previous_error = str(data.get("regeneration", {}).get("last_error") or "").lower()
        needs_escalation = previous_state == "retry_required" or "structural mismatch" in previous_error or "identity validation" in previous_error
        if needs_escalation:
            start_level = _highest_attempted_prompt_level(data) + 1
            if start_level > _max_prompt_level():
                log(
                    f"[BLOCK] {ref} | regeneration | strict fallback already exhausted on a previous run | no additional expensive attempt allowed",
                    log_file,
                )
                return
        else:
            start_level = 0
        working, canvas = _generate_until_approved(client, source, ref, meta_path, data, log_file, start_level=start_level)
        if working is None:
            return
    else:
        existing = _locate_working_image(ref, data)
        if existing is None:
            log(f"[FAIL] {ref} | regeneration | metadata says completed but working image is missing", log_file)
            return
        working = existing
        if not canvas.exists():
            fit_to_canvas(working, canvas)
        log(f"[SKIP] {ref} | regeneration | status.regenpic=true | using={working.name}", log_file)

        if not _logo_zone_clear(data):
            width, height, max_occupancy = _safe_zone_settings()
            ok, occupancy = safe_zone_ok(canvas, width, height, max_occupancy)
            save(meta_path, data)
            log(f"[OK] {ref} | canvas layout | existing candidate | logo_zone_clear={ok} | occupancy={occupancy:.2%}", log_file)

        if not (stage_completed(data.get("identity_validation")) and bool((data.get("identity_validation") or {}).get("pass"))):
            accepted = _validate_existing_candidate(client, source, canvas, ref, meta_path, data, log_file)
            if accepted is None:
                return
            if not accepted:
                data["regeneration"].update({
                    "status": "retry_required",
                    "last_error": "Identity validation structurally rejected existing candidate",
                    "completed_at": None,
                })
                save(meta_path, data)
                next_level = _highest_attempted_prompt_level(data) + 1
                if next_level > _max_prompt_level():
                    log(
                        f"[BLOCK] {ref} | identity validation | existing candidate rejected but strict fallback is already exhausted",
                        log_file,
                    )
                    return
                working, canvas = _generate_until_approved(client, source, ref, meta_path, data, log_file, start_level=next_level)
                if working is None:
                    return
        else:
            log(f"[SKIP] {ref} | identity validation | already approved", log_file)

    if not stage_completed(data.get("ocr"), allow_manual_override=True):
        ocr_model_primary = os.getenv("OCR_MODEL_PRIMARY", "gpt-5.6-luna")
        ocr_model_fallback = os.getenv("OCR_MODEL_FALLBACK", "gpt-5.6-sol")
        log(
            f"[RUN] {ref} | OCR | primary={ocr_model_primary} | fallback={ocr_model_fallback} | "
            f"prompt={OCR_PROMPT_VERSION} | mode=dual-image-cropped-upscaled-fallback",
            log_file,
        )
        log(
            f"[OPENAI-REQUEST] {ref} | stage=ocr | images=2 | original={source.name} | regenerated={canvas.name} | "
            f"original_authority=true | crop_mode=tight_component_plus_marking | detail=original",
            log_file,
        )
        try:
            result = extract(client, source, canvas)
            record_api_stage(data, "ocr", result.get("_api_accounting"))
            data["part_number"] = result.get("PartNumber")
            data["product_title"] = deterministic_product_title(data["part_number"]) if data.get("part_number") else None
            # OCR observations are evidence only. Canonical manufacturer/country
            # are reserved for Phase 2 after exact PartNumber identity is proven.
            data["manufacturer"] = None
            data["country"] = None
            data["ocr"].update({
                "status": "completed",
                "model": result.get("_model_used") or ocr_model_primary,
                "models_tried": result.get("_models_tried") or [ocr_model_primary],
                "fallback_used": bool(result.get("_fallback_used")),
                "ocr_view_mode": result.get("_ocr_view_mode") or "dual-image-cropped-upscaled",
                "prompt_version": OCR_PROMPT_VERSION,
                "visible_lines_original": result.get("visible_lines_original") or [],
                "visible_lines_regenerated": result.get("visible_lines_regenerated") or [],
                "visible_lines": result.get("visible_lines") or [],
                "primary_code": result.get("primary_code"),
                "part_number_segments": result.get("part_number_segments") or [],
                "part_number_layout": result.get("part_number_layout"),
                "part_number_confidence": result.get("part_number_confidence") or "unreadable",
                "image_source_decision": result.get("image_source_decision") or "uncertain",
                "secondary_codes": result.get("secondary_codes") or [],
                "comparison_conflicts": result.get("comparison_conflicts") or [],
                "critical_character_review": result.get("critical_character_review") or [],
                "candidate_part_numbers": result.get("candidate_part_numbers") or [],
                "selected_candidate_reason": result.get("selected_candidate_reason"),
                "manufacturer_marking": result.get("manufacturer"),
                "country_marking": result.get("country"),
                "notes": result.get("notes"),
                "last_error": None,
                "completed_at": utc_now(),
            })
            save(meta_path, data)
            log(
                f"[OPENAI-RESPONSE] {ref} | stage=ocr | model_used={data['ocr'].get('model')} | "
                f"models_tried={data['ocr'].get('models_tried')} | fallback_used={data['ocr'].get('fallback_used')} | "
                f"PartNumber={data['part_number']} | confidence={data['ocr'].get('part_number_confidence')} | "
                f"source_decision={data['ocr'].get('image_source_decision')} | segments={data['ocr'].get('part_number_segments')} | "
                f"conflicts={data['ocr'].get('comparison_conflicts')}",
                log_file,
            )
            log(
                f"[OK] {ref} | OCR | PartNumber={data['part_number']} | manufacturer_marking={data['ocr'].get('manufacturer_marking')} | "
                f"country_marking={data['ocr'].get('country_marking')} | visible_lines={data['ocr']['visible_lines']}",
                log_file,
            )
        except Exception as exc:
            data["ocr"].update({"status": "failed", "last_error": str(exc)})
            save(meta_path, data)
            log(f"[FAIL] {ref} | OCR | {exc}", log_file)
            return
    else:
        log(f"[SKIP] {ref} | OCR | ocr.status=completed | PartNumber={data.get('part_number')}", log_file)

    if not data.get("part_number"):
        log(f"[BLOCK] {ref} | PartNumber empty | ocr_confidence={data.get('ocr', {}).get('part_number_confidence')} | Phase2/logo/finalization stopped", log_file)
        return

    try:
        old_meta = meta_path
        meta_path = rename_metadata_to_partnumber(ROOT, meta_path, data)
        if old_meta.resolve() != meta_path.resolve():
            log(f"[OK] {ref} | metadata rename | {old_meta.name} -> {meta_path.name}", log_file)
        else:
            log(f"[SKIP] {ref} | metadata rename | already named {meta_path.name}", log_file)
    except Exception as exc:
        log(f"[FAIL] {ref} | metadata rename | {exc}", log_file)
        return

    # PartNumber is now stable and metadata filename is canonical.
    # The integrated V1 orchestrator emits this immediately to the asynchronous
    # Phase-2 worker while Phase 1 continues logo/final image processing.
    if on_part_number_ready:
        on_part_number_ready(meta_path, data, ref)
    else:
        _phase2_enqueue(phase2_coordinator, meta_path, ref, log_file)

    logo = ROOT / "assets" / "store_logo.png"
    composed = ROOT / "output" / f"{data['part_number']}.png"
    if not stage_completed(data.get("logo")):
        log(f"[RUN] {ref} | logo overlay | logo={logo.name} | target={composed.name}", log_file)
        try:
            overlay_logo(
                canvas,
                logo,
                composed,
                max_width=int(os.getenv("LOGO_MAX_WIDTH", "260")),
                max_height=int(os.getenv("LOGO_MAX_HEIGHT", "260")),
                margin=int(os.getenv("LOGO_MARGIN", "40")),
            )
            data["logo"].update({
                "status": "completed",
                "file": portable_path(ROOT, logo),
                "last_error": None,
                "completed_at": utc_now(),
            })
            save(meta_path, data)
            log(f"[OK] {ref} | logo overlay | file={composed.name}", log_file)
        except Exception as exc:
            data["logo"].update({"status": "failed", "last_error": str(exc)})
            save(meta_path, data)
            log(f"[FAIL] {ref} | logo overlay | {exc}", log_file)
            return
    else:
        if not composed.exists():
            log(f"[FAIL] {ref} | logo overlay | logo.status=completed but composed PNG is missing", log_file)
            return
        log(f"[SKIP] {ref} | logo overlay | logo.status=completed | using={composed.name}", log_file)

    final = ROOT / "Final" / f"{data['part_number']}.webp"
    if not image_finalized(data):
        min_kb = int(os.getenv("MIN_KB", "50"))
        max_kb = int(os.getenv("MAX_KB", "100"))
        log(
            f"[RUN] {ref} | final optimization | format=WEBP | size=1254x1254 | target={min_kb}-{max_kb}KB",
            log_file,
        )
        try:
            quality, size_kb = optimize_final(composed, final, min_kb, max_kb)
            target_note = (
                "within-target" if min_kb <= size_kb <= max_kb
                else "below-target" if size_kb < min_kb
                else "above-target"
            )
            log(
                f"[OK] {ref} | final optimization candidate | file={final.name} | size={size_kb:.2f}KB | q={quality} | {target_note}",
                log_file,
            )

            seen = set()
            for path in (working, canvas, composed):
                try:
                    key = path.resolve()
                except Exception:
                    key = path
                if key in seen:
                    continue
                seen.add(key)
                if path.exists():
                    path.unlink()
                    log(f"[CLEAN] {ref} | removed intermediate | {path.name}", log_file)

            data["image_optimization"].update({
                "status": "completed",
                "format": "WEBP",
                "width": 1254,
                "height": 1254,
                "size_kb": round(size_kb, 2),
                "quality": quality,
                "file": portable_path(ROOT, final),
                "last_error": None,
                "completed_at": utc_now(),
            })
            save(meta_path, data)
            estimated_cost = data.get("diagnostics", {}).get("api_accounting", {}).get("estimated_total_usd")
            log(
                f"[FINALIZED] {ref} | PartNumber={data['part_number']} | Final={final.name} | "
                f"metadata={meta_path.name} | estimated_api_cost_usd={estimated_cost}",
                log_file,
            )
        except Exception as exc:
            data["image_optimization"].update({"status": "failed", "last_error": str(exc)})
            save(meta_path, data)
            log(f"[FAIL] {ref} | final optimization/cleanup | {exc}", log_file)
            return
    else:
        log(f"[SKIP] {ref} | final optimization | image_optimization.status=completed", log_file)
        log(f"[FINALIZED] {ref} | PartNumber={data['part_number']} | metadata={meta_path.name}", log_file)


def main():
    load_dotenv(ROOT / ".env")
    log_file = ROOT / "logs" / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log"
    log("[BOOT] Tavakol Integrated Phase 1 + Phase 2 V2.0 starting", log_file)

    try:
        client = run_preflight(ROOT)
        log("[OK] preflight | API connection + directories + store_logo.png verified", log_file)
    except Exception as exc:
        log(f"[PREFLIGHT FAIL] {exc}", log_file)
        return 1

    try:
        phase2_coordinator = _build_phase2_coordinator(log_file)
    except Exception as exc:
        log(f"[PHASE2 INIT FAIL] {type(exc).__name__}: {exc}", log_file)
        return 1

    # Resume-safe startup: enqueue metadata that Phase 1 completed on older runs.
    if phase2_coordinator is not None:
        try:
            existing = phase2_coordinator.pipeline.eligible_paths()
            log(f"[PHASE2-RESUME] eligible_existing={len(existing)}", log_file)
            for path in existing:
                phase2_coordinator.enqueue(path)
        except Exception as exc:
            log(f"[PHASE2-RESUME-ERROR] {type(exc).__name__}: {exc}", log_file)

    images = find_images(ROOT)
    log(f"[DISCOVER] Found {len(images)} image(s) in input/", log_file)
    for image in images:
        try:
            process_one(client, image, log_file, phase2_coordinator)
        except Exception:
            log(f"[UNHANDLED ERROR] {image.name}", log_file)
            with log_file.open("a", encoding="utf-8") as f:
                traceback.print_exc(file=f)
            traceback.print_exc()

    if phase2_coordinator is not None:
        try:
            flushed = phase2_coordinator.flush()
            log(f"[PHASE2-FLUSH] processed_remaining={flushed}", log_file)
        except Exception as exc:
            log(f"[PHASE2-FLUSH-ERROR] {type(exc).__name__}: {exc}", log_file)

    log("[DONE] Integrated Phase 1 + Phase 2 pipeline run completed", log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
