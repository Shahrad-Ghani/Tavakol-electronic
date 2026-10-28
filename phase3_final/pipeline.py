import os
from pathlib import Path

from dotenv import load_dotenv

from .io_utils import read_json, write_json
from .schemas import validate_json
from .router import choose_mode, validate_route_contract
from .prompt_builder import load_prompts, build_user_payload
from .agent import ContentAgent
from .assembly import sanitize_agent_output, build_attempt_bundle
from .internal_link_policy import select_anchor, inject_policy_link, audit_policy_link
from .content_contract import validate_content_contract
from .feedback import build_validator_feedback
from .html_renderer import render_html
from .candidate_selector import select_best_candidate
from .fact_safety import project_safe_facts, validate_fact_safety
from .deterministic_repairs import (
    repair_body_structure, repair_snippet_and_alts,
    merge_duplicate_faq_sections, repair_high_keyword_density,
    remove_duplicate_sentences, remove_repeated_part_number_warnings,
    repair_excessive_word_count, cleanup_banned_style_phrases, repair_empty_sections,
    fine_trim_near_word_ceiling, ensure_intro_heading,
)
from .style_contract import validate_style_contract
from .tone_editor import ToneNaturalnessEditor
from .prompt_registry import build_prompt_manifest
from .cost_accounting import stage_record, summarize_stage_records
from .evaluation_scorecard import build_product_scorecard
from .seo_snippet_agent import SeoSnippetAgent, DeterministicSeoSnippetAgent
from phase3b_validator.engine import analyze_bundle


class Phase3FinalPipeline:
    def __init__(self, root, cheap_agent=None, expensive_agent=None, tone_editor=None, final_auditor=None, seo_agent=None):
        load_dotenv()
        self.root = Path(root)
        self.cfg = read_json(self.root/'config'/'phase3_final.json')
        self.store = read_json(self.root/'config'/'store_profile.json')
        cheap_model = os.getenv('CHEAP_WRITER_MODEL', self.cfg.get('cheap_writer_model', 'gpt-5.6-luna'))
        common = (self.root/'schema'/'agent_output.schema.json', self.cfg['max_output_tokens'], self.root/'schema'/'body_repair.schema.json')
        self.cheap_agent = cheap_agent or ContentAgent(cheap_model, *common, reasoning_effort=self.cfg.get('writer_reasoning_effort','medium'))
        # V2.1.1: expensive tier is disabled. Config keeps a Luna compatibility alias
        # only so stale V2 startup code cannot crash on a missing key.
        self.expensive_agent = None
        self.tone_editor = tone_editor or ToneNaturalnessEditor(self.root, self.cfg)
        self.final_auditor = final_auditor
        self.seo_agent = seo_agent or (DeterministicSeoSnippetAgent() if cheap_agent is not None else SeoSnippetAgent(self.root))
        self.prompt_manifest = build_prompt_manifest(self.root)

    @staticmethod
    def _all_hard_gates_pass(hard_gates):
        return all(x.get('status') != 'FAIL' for x in (hard_gates or {}).values())

    _EDITORIAL_METRIC_FAILURES = {
        'keyword_density_not_severely_outside_target',
        'word_count_not_severely_outside_target',
    }

    @staticmethod
    def _ready(a, threshold):
        """Generation/retry readiness only. SEO >= threshold may still avoid extra writer calls.

        Altimate V1.1 deliberately does NOT use this helper as the publication gate.
        """
        return bool(a.get('hard_gate_pass') and a.get('fact_safety_pass') and a.get('contract_pass') and a.get('score',0) >= threshold)

    @classmethod
    def _core_contract_pass(cls, a):
        """Return True when all non-editorial structural requirements pass.

        SEO density and word-count envelope are quality metrics in V1.1. They may
        trigger local/editorial cleanup, but they are not hard publication gates.
        """
        failures = set(((a.get('structure') or {}).get('failures') or []))
        return not (failures - cls._EDITORIAL_METRIC_FAILURES)

    @staticmethod
    def _tone_ready(a):
        """V4 tone gate: only absolute hard gates/fact-safety may block tone editing."""
        return bool(a.get('hard_gate_pass') and a.get('fact_safety_pass'))

    @classmethod
    def _editorial_ready(cls, a):
        """Safe enough for Tone Editor / facts-only audit.

        Hard gates and fact safety remain absolute. Missing required sections, links,
        FAQ answers, etc. remain blocking. Only density/word-count metric failures are
        allowed through to the editor. SEO score itself is never checked here.
        """
        return bool(a.get('hard_gate_pass') and a.get('fact_safety_pass') and cls._core_contract_pass(a))

    @classmethod
    def _publication_ready(cls, a, *, tone_pass, semantic_pass):
        """V1.1 frozen publication gate; SEO score is intentionally absent."""
        return bool(cls._editorial_ready(a) and tone_pass and semantic_pass)

    def _facts(self, product, origin_path, content_mode):
        if content_mode != 'TECHNICAL_LIGHT':
            return None
        fp = product.get('source',{}).get('facts_path')
        if not fp:
            return None
        p = Path(fp)
        if not p.is_absolute():
            p = (Path(origin_path).parent/p).resolve()
        return project_safe_facts(read_json(p)) if p.exists() else None

    def _evaluate(self, *, product, origin_path, content_mode, agent_raw, outdir, artifact_name, attempt_number,
                  model_tier, api_meta, link_selection, generation_mode, allow_body_repairs=True,
                  allow_link_injection=True, inherited_repairs=None):
        """Evaluate one candidate.

        Altimate V1.1 invariant: after Tone Editor, callers set allow_body_repairs=False and
        allow_link_injection=False, therefore this function performs audit only
        and cannot insert any customer-facing content.
        """
        # V3.0: FULL_GENERATION is validated exactly against the LLM schema, which
        # intentionally forbids product_title. Internal repair/tone candidates are
        # derived from an already-sanitized candidate and therefore carry the
        # deterministic product_title; remove only that exact deterministic field
        # before re-validating the LLM-owned fields.
        validation_raw = dict(agent_raw)
        if generation_mode != 'FULL_GENERATION':
            from core.category_registry import product_title
            expected_title = product_title(product['identity']['part_number'], product['identity'].get('product_category'))
            if validation_raw.get('product_title') == expected_title:
                validation_raw.pop('product_title', None)
        validate_json(validation_raw, self.root/'schema'/'agent_output.schema.json')
        agent = sanitize_agent_output(product, validation_raw)
        agent, field_repairs = repair_snippet_and_alts(product, agent)
        structure_repairs = []
        body = agent.get('body_markdown','')
        if allow_body_repairs:
            body, structure_repairs = repair_body_structure(product, body)
        if allow_link_injection:
            md, link_audit = inject_policy_link(body, link_selection)
        else:
            md = body.strip() + '\n'
            link_audit = audit_policy_link(md, link_selection)
        agent['body_markdown'] = md
        agent['internal_links'] = [{'url':link_selection['target_url'],'anchor':link_selection['anchor']}]

        # V1 integrated runtime: content stays in JSON/in-memory. No generated .md files.
        bundle_path = outdir/'attempts'/f'{artifact_name}.bundle.json'
        bundle = build_attempt_bundle(product, content_mode, agent, md.strip()+'\n', attempt_number, self.cfg['agent_version'])
        write_json(bundle_path, bundle)
        analysis = analyze_bundle(bundle_path, self.root/'config'/'rankmath_reference_product_v0.1.json')
        score = int(analysis['score'])
        hard_gates = analysis.get('_hard_gates',{})
        hard_pass = self._all_hard_gates_pass(hard_gates)
        structure = validate_content_contract(bundle, md, product['identity']['part_number'], link_selection, seo_metrics=analysis['_metrics'], policy_cfg=self.cfg)
        facts = self._facts(product, origin_path, content_mode)
        visible = '\n'.join([md, str(agent.get('product_title') or ''), str(agent.get('seo_title') or ''), str(agent.get('meta_description') or '')])
        fact_safety = validate_fact_safety(visible, facts, content_mode, verified_identity=product.get('identity',{}))
        feedback = build_validator_feedback(analysis, structure, link_selection, fact_safety=fact_safety, hard_gates=hard_gates)
        style = validate_style_contract(md)
        deterministic = list(inherited_repairs or []) + field_repairs + structure_repairs
        meta = {
            'score':score, 'api':api_meta, 'model_tier':model_tier, 'generation_mode':generation_mode,
            'hard_gates':hard_gates, 'structure_contract':structure, 'fact_safety':fact_safety,
            'style_prefilter':style, 'link_injection':link_audit, 'validator_feedback':feedback,
            'seo_scoring':analysis['_scoring'], 'seo_metrics':analysis['_metrics'],
            'deterministic_repairs':deterministic,
            'post_tone_content_insertion': False if not allow_body_repairs and not allow_link_injection else None,
        }
        meta_path = outdir/'attempts'/f'{artifact_name}.meta.json'
        write_json(meta_path, meta)
        return {
            'attempt':attempt_number,'artifact_name':artifact_name,'score':score,'contract_pass':bool(structure['passed']),
            'hard_gate_pass':hard_pass,'hard_gates':hard_gates,'fact_safety_pass':bool(fact_safety['passed']),
            'fact_safety':fact_safety,'agent':agent,'bundle':bundle,'analysis':analysis,'structure':structure,
            'style_prefilter':style,'bundle_path':bundle_path,'meta_path':meta_path,'feedback':feedback,
            'generation_mode':generation_mode,'model_tier':model_tier,'api':api_meta,
        }

    def _writer_payload(self, origin_path, product, content_mode, previous, feedback, link_selection, fact_safety_repair=None):
        return build_user_payload(
            origin_path, product, content_mode, self.store, previous=previous,
            validator_feedback=feedback, link_selection=link_selection,
            fact_safety_repair=fact_safety_repair,
        )

    def _pre_tone_deterministic_repair(self, selected, *, product, origin_path, content_mode, outdir, link_selection):
        if not (selected.get('hard_gate_pass') and selected.get('fact_safety_pass')):
            return selected, None
        body = selected['agent']['body_markdown']
        repairs = []
        for fn in (merge_duplicate_faq_sections, remove_duplicate_sentences, remove_repeated_part_number_warnings):
            body2, rs = fn(body) if fn is not remove_repeated_part_number_warnings else fn(body)
            body = body2; repairs.extend(rs)

        # Altimate V1 local normalizer order is frozen. All structural/length cleanup
        # happens first; density repair is the LAST local normalization step so
        # later deletions cannot push density back above the target.
        from phase3b_validator.markdown_tools import words, strip_markdown
        from phase3b_validator.metrics import count_exact
        pn = product['identity']['part_number']
        wpol = self.cfg['technical_target_words'] if content_mode == 'TECHNICAL_LIGHT' else self.cfg['commercial_target_words']
        hard_max = int(wpol['max']) + int(self.cfg.get('word_count_soft_tolerance_words', 120))

        if self.cfg.get('deterministic_length_repair_enabled', True) and len(words(body)) > hard_max:
            body, rs = repair_excessive_word_count(
                body, pn, hard_max=hard_max, target_max=max(int(wpol['max']), hard_max - 20)
            )
            repairs.extend(rs)

        body, rs = cleanup_banned_style_phrases(body)
        repairs.extend(rs)
        body, rs = repair_empty_sections(product, body)
        repairs.extend(rs)

        # Fine trim is only for near-ceiling leftovers such as 777 vs 770.
        if self.cfg.get('fine_length_trim_enabled', True) and len(words(body)) > hard_max:
            body, rs = fine_trim_near_word_ceiling(
                body, pn, hard_max=hard_max,
                margin_words=int(self.cfg.get('fine_length_trim_margin_words', 30)),
            )
            repairs.extend(rs)

        # LAST STEP: exact-PN density normalization in prose only.
        wc = len(words(body))
        density = (count_exact(strip_markdown(body), pn) / wc * 100.0) if wc else 0.0
        target_max = float(self.cfg.get('keyword_density_target',{}).get('max',1.5))
        if self.cfg.get('deterministic_density_repair_enabled', True) and density > target_max:
            from core.category_registry import density_phrase
            body, rs = repair_high_keyword_density(body, pn, target_max=target_max, replacement_phrase=density_phrase(product['identity'].get('product_category')))
            repairs.extend(rs)

        if not repairs:
            return selected, None

        raw = dict(selected['agent']); raw['body_markdown'] = body
        det = self._evaluate(
            product=product, origin_path=origin_path, content_mode=content_mode, agent_raw=raw, outdir=outdir,
            artifact_name='pre_tone_deterministic', attempt_number=selected['attempt'], model_tier='DETERMINISTIC', api_meta=None,
            link_selection=link_selection, generation_mode='PRE_TONE_DETERMINISTIC_REPAIR',
            allow_body_repairs=False, allow_link_injection=False, inherited_repairs=repairs,
        )
        return select_best_candidate([selected, det]), det

    def _post_tone_cleanup(self, body_markdown, part_number):
        """Non-density cleanup after Tone Editor.

        V1.2 sequencing patch: exact-PN density repair is allowed only in the
        pre-Tone local normalizer. After Tone Editor, the customer-facing prose
        must not be mutated again to force density. Local validators still measure
        and report the final density, but no post-Tone PN substitution is allowed.

        No section/link/fact insertion is allowed here. URLs have already been
        byte-protected by ToneNaturalnessEditor.
        """
        body, repairs = cleanup_banned_style_phrases(body_markdown)
        return body, repairs

    def _tone_candidate_ok(self, tone, evaluated, threshold):
        natural_ok = int(tone.get('naturalness_score',0)) >= int(self.cfg.get('tone_naturalness_minimum',80))
        # Altimate V1.1 freeze patch: SEO score/density/word-count are quality metrics,
        # not publication gates. Hard gates, fact safety and core structure remain absolute.
        return bool(
            tone.get('status') != 'REVIEW_REQUIRED'
            and not tone.get('technical_facts_changed')
            and natural_ok
            and evaluated['style_prefilter']['passed']
            and self._editorial_ready(evaluated)
        )

    def _read_extraction_api(self, product, key):
        p = product.get('source',{}).get(key)
        if not p:
            return None
        try:
            obj = read_json(Path(p))
            return obj.get('api')
        except Exception:
            return None

    def _cost_summary(self, product, writer_attempts, tone_api_records, audit_api_records):
        pricing = self.cfg.get('model_pricing_per_1m_usd',{})
        records = []
        primary = self._read_extraction_api(product, 'primary_extraction_path')
        fallback = self._read_extraction_api(product, 'fallback_extraction_path')
        if primary:
            records.append(stage_record('pdf_fact_extraction_primary', primary, pricing))
        if fallback:
            records.append(stage_record('pdf_fact_extraction_fallback', fallback, pricing))
        for a in writer_attempts:
            if a.get('api'):
                records.append(stage_record(a['artifact_name'], a['api'], pricing))
        for idx, api in enumerate(tone_api_records, 1):
            if api:
                records.append(stage_record(f'tone_editor_attempt_{idx}', api, pricing))
        for idx, api in enumerate(audit_api_records, 1):
            if api:
                records.append(stage_record(f'facts_only_audit_{idx}', api, pricing))
        return summarize_stage_records(records, pricing_basis=self.cfg.get('pricing_basis'))

    def process_product(self, product, origin_path, output_root, force=False):
        origin_path, output_root = Path(origin_path).resolve(), Path(output_root).resolve()
        validate_route_contract(product)
        pn = product['identity']['part_number']
        outdir = output_root/pn
        final_path = outdir/'product.json'
        if final_path.exists() and not force:
            cached = read_json(final_path)
            return {'product':pn,'skipped':True,'score':int(cached['validation']['final_seo_score']), 'status':cached['validation']['seo_status'],
                    'disposition':cached['validation']['disposition'],'publishable':bool(cached['validation']['publishable']),
                    'final_path':str(final_path),'html_path':str(outdir/'content.html')}
        outdir.mkdir(parents=True,exist_ok=True); (outdir/'attempts').mkdir(exist_ok=True)
        content_mode = choose_mode(product)
        instructions = load_prompts(self.root, content_mode)
        threshold = int(self.cfg['seo_threshold'])
        link_selection = select_anchor(self.root, pn, product['identity'].get('product_category') or 'ic')
        attempts=[]

        # CHEAP ATTEMPT 1 — full generation, prompt explicitly aligned to structure contract.
        payload = self._writer_payload(origin_path, product, content_mode, None, None, link_selection)
        raw, api = self.cheap_agent.generate(instructions, payload)
        a1 = self._evaluate(product=product, origin_path=origin_path, content_mode=content_mode, agent_raw=raw, outdir=outdir,
                            artifact_name='cheap_attempt_1', attempt_number=1, model_tier='CHEAP', api_meta=api,
                            link_selection=link_selection, generation_mode='FULL_GENERATION')
        attempts.append(a1)

        # CHEAP ATTEMPT 2 — targeted body repair only.
        if not self._ready(a1, threshold):
            retry_inst = instructions + '\n\n' + (self.root/'prompts'/'retry.md').read_text(encoding='utf-8')
            retry_inst += '\n\nALTIMATE V1 LENGTH/DENSITY RULE: hit the requested word envelope and PN occurrence budget exactly by deleting filler/repetition, never by changing technical facts.'
            payload = self._writer_payload(origin_path, product, content_mode, {'score':a1['score'],'agent_output':a1['agent']}, a1['feedback'], link_selection)
            body, api = self.cheap_agent.repair_body(retry_inst, payload)
            raw2 = dict(a1['agent']); raw2['body_markdown'] = body['body_markdown']
            a2 = self._evaluate(product=product, origin_path=origin_path, content_mode=content_mode, agent_raw=raw2, outdir=outdir,
                                artifact_name='cheap_attempt_2', attempt_number=2, model_tier='CHEAP', api_meta=api,
                                link_selection=link_selection, generation_mode='TARGETED_BODY_REPAIR')
            attempts.append(a2)

        selected = select_best_candidate(attempts)

        # V4.0.1: if the writer still violates Fact Safety, perform one explicit
        # targeted repair. The model receives its previous body plus the exact
        # validator failures and may only rewrite the body using verified facts.
        fact_safety_repairs_used = 0
        max_fact_repairs = int(self.cfg.get('fact_safety_repair_max_attempts', 1))
        while (not selected.get('fact_safety_pass')) and fact_safety_repairs_used < max_fact_repairs:
            fact_safety_repairs_used += 1
            repair_inst = instructions + '\n\n' + (self.root/'prompts'/'fact_safety_retry.md').read_text(encoding='utf-8')
            repair_context = {
                'original_content': selected['agent'].get('body_markdown') or '',
                'errors': (selected.get('fact_safety') or {}).get('failures') or [],
            }
            payload = self._writer_payload(
                origin_path, product, content_mode,
                {'score': selected['score'], 'agent_output': selected['agent']},
                selected['feedback'], link_selection, fact_safety_repair=repair_context,
            )
            body, api = self.cheap_agent.repair_body(repair_inst, payload)
            repaired_raw = dict(selected['agent'])
            repaired_raw['body_markdown'] = body['body_markdown']
            attempt_no = max(int(a.get('attempt', 0)) for a in attempts) + 1
            repaired = self._evaluate(
                product=product, origin_path=origin_path, content_mode=content_mode,
                agent_raw=repaired_raw, outdir=outdir,
                artifact_name=f'fact_safety_repair_{fact_safety_repairs_used}',
                attempt_number=attempt_no, model_tier='CHEAP', api_meta=api,
                link_selection=link_selection, generation_mode='FACT_SAFETY_TARGETED_REPAIR',
            )
            attempts.append(repaired)
            selected = select_best_candidate(attempts)

        # Cost-first rule: local deterministic repairs run before any optional model escalation.
        # V2.1 has no expensive writer tier, so local repair is always the final cost-control step.
        selected, deterministic_candidate = self._pre_tone_deterministic_repair(
            selected, product=product, origin_path=origin_path, content_mode=content_mode,
            outdir=outdir, link_selection=link_selection,
        )

        expensive_used = False
        escalation_reason = 'DISABLED_IN_V2.1_LUNA_ONLY'

        # Freeze patch V1.1: SEO <80 and density/word-count metric failures do not block Tone/Audit.
        local_ready = self._tone_ready(selected)
        tone_record = {'status':'NOT_RUN','reason':'MAIN_CONTENT_MISSING','attempts':[],'ai_like_style_score_diagnostic_only':True}
        final_candidate = selected
        tone_pass = False
        tone_api_records = []

        if bool((selected.get('agent') or {}).get('body_markdown')) and self.cfg.get('tone_editor_required',True):
            safe_facts = self._facts(product, origin_path, content_mode)
            tone, tone_api = self.tone_editor.edit(part_number=pn, body_markdown=selected['agent']['body_markdown'], verified_facts=safe_facts,
                                                   store_profile=self.store, required_anchor_phrase=link_selection['anchor'])
            tone_api_records.append(tone_api)
            write_json(outdir/'tone_editor.attempt_1.raw.json', {'result':tone,'api':tone_api})
            tone_body, tone_cleanup_1 = self._post_tone_cleanup(tone['body_markdown'], pn)
            traw = dict(selected['agent']); traw['body_markdown'] = tone_body
            te1 = self._evaluate(product=product, origin_path=origin_path, content_mode=content_mode, agent_raw=traw, outdir=outdir,
                                 artifact_name='tone_edited_1', attempt_number=selected['attempt'], model_tier='TONE_EDITOR', api_meta=tone_api,
                                 link_selection=link_selection, generation_mode='TONE_EDIT', allow_body_repairs=False, allow_link_injection=False, inherited_repairs=tone_cleanup_1)
            tone_pass = self._tone_candidate_ok(tone, te1, threshold)
            tone_attempts = [{'attempt':1,'result':tone,'api':tone_api,'local_validation':{
                'seo_score':te1['score'],'hard_gate_pass':te1['hard_gate_pass'],'fact_safety_pass':te1['fact_safety_pass'],
                'structure_pass':te1['contract_pass'],'style_pass':te1['style_prefilter']['passed']}}]
            if tone_pass:
                final_candidate = te1
            elif int(self.cfg.get('tone_editor_max_attempts',2)) >= 2:
                tone2, tone2_api = self.tone_editor.retry(
                    part_number=pn, body_markdown=tone['body_markdown'], verified_facts=safe_facts, store_profile=self.store,
                    required_anchor_phrase=link_selection['anchor'], validator_feedback=te1['feedback'], previous_tone_result=tone,
                )
                tone_api_records.append(tone2_api)
                write_json(outdir/'tone_editor.attempt_2.raw.json', {'result':tone2,'api':tone2_api})
                tone_body_2, tone_cleanup_2 = self._post_tone_cleanup(tone2['body_markdown'], pn)
                traw2 = dict(selected['agent']); traw2['body_markdown'] = tone_body_2
                te2 = self._evaluate(product=product, origin_path=origin_path, content_mode=content_mode, agent_raw=traw2, outdir=outdir,
                                     artifact_name='tone_edited_2', attempt_number=selected['attempt'], model_tier='TONE_EDITOR', api_meta=tone2_api,
                                     link_selection=link_selection, generation_mode='TARGETED_TONE_RETRY', allow_body_repairs=False, allow_link_injection=False, inherited_repairs=tone_cleanup_2)
                tone_pass = self._tone_candidate_ok(tone2, te2, threshold)
                tone_attempts.append({'attempt':2,'result':tone2,'api':tone2_api,'local_validation':{
                    'seo_score':te2['score'],'hard_gate_pass':te2['hard_gate_pass'],'fact_safety_pass':te2['fact_safety_pass'],
                    'structure_pass':te2['contract_pass'],'style_pass':te2['style_prefilter']['passed']}})
                if tone_pass:
                    final_candidate = te2
            final_tone = tone_attempts[-1]
            tone_record = {
                'status':'PASS' if tone_pass else 'REVIEW_REQUIRED',
                'attempted': True, 'fallback_to_pre_tone': not tone_pass,
                'attempts':tone_attempts,
                'result':final_tone['result'], 'api':final_tone['api'], 'local_validation':final_tone['local_validation'],
                'ai_like_style_score_diagnostic_only':True,
            }
        elif local_ready:
            tone_pass = True; tone_record={'status':'SKIPPED_BY_CONFIG','attempts':[],'ai_like_style_score_diagnostic_only':True}

        # V4.0.4: deterministic introduction-H2 integrity repair. This runs after
        # Tone Editor so the model cannot remove the heading afterwards, but before
        # final SEO snippet validation / semantic audit / HTML rendering. No model
        # or API call is made. Natural variants containing both "معرفی" and the
        # exact PN are accepted; otherwise the category-aware canonical H2 is added.
        intro_body, intro_heading_record, intro_repairs = ensure_intro_heading(
            product, final_candidate['agent'].get('body_markdown') or ''
        )
        if intro_repairs:
            iraw = dict(final_candidate['agent'])
            iraw['body_markdown'] = intro_body
            final_candidate = self._evaluate(
                product=product, origin_path=origin_path, content_mode=content_mode, agent_raw=iraw, outdir=outdir,
                artifact_name='intro_header_final', attempt_number=final_candidate['attempt'], model_tier='DETERMINISTIC', api_meta=None,
                link_selection=link_selection, generation_mode='INTRO_HEADER_REPAIR', allow_body_repairs=False, allow_link_injection=False,
                inherited_repairs=intro_repairs,
            )
        # Re-check after the repair and fail closed if the deterministic invariant
        # somehow did not survive evaluation.
        _intro_verify_body = final_candidate['agent'].get('body_markdown') or ''
        _intro_verify, intro_heading_record, _ = ensure_intro_heading(product, _intro_verify_body)
        if intro_heading_record.get('programmatic_repair_applied'):
            # This branch would imply evaluation removed the heading; that should
            # never happen because _evaluate performs audit-only body handling here.
            raise RuntimeError(f'INTRO_HEADER_INVARIANT_FAILED for {pn}')
        intro_heading_record['programmatic_repair_applied'] = bool(intro_repairs)
        local_ready = self._tone_ready(final_candidate)

        # V4: SEO title/meta are owned by an independent snippet agent. The main writer's
        # snippet is provisional only. Run this once after body/tone selection, then
        # re-evaluate the candidate so Rank Math metrics/fact safety reflect the canonical snippet.
        seo_record = {'status':'NOT_RUN','api':None}
        if bool((final_candidate.get('agent') or {}).get('body_markdown')):
            safe_facts = self._facts(product, origin_path, content_mode)
            seo_out, seo_api = self.seo_agent.generate(
                part_number=pn, category_key=product['identity'].get('product_category') or 'ic',
                manufacturer=product['identity'].get('manufacturer'), safe_facts=safe_facts,
            )
            sraw = dict(final_candidate['agent'])
            sraw['seo_title'] = seo_out['seo_title']
            sraw['meta_description'] = seo_out['meta_description']
            final_candidate = self._evaluate(
                product=product, origin_path=origin_path, content_mode=content_mode, agent_raw=sraw, outdir=outdir,
                artifact_name='seo_snippet_final', attempt_number=final_candidate['attempt'], model_tier='SEO_SNIPPET', api_meta=seo_api,
                link_selection=link_selection, generation_mode='SEO_SNIPPET_FINALIZATION', allow_body_repairs=False, allow_link_injection=False,
            )
            seo_record = {'status':'COMPLETED','api':seo_api,'seo_title':seo_out['seo_title'],'meta_description':seo_out['meta_description']}
            local_ready = self._tone_ready(final_candidate)

        final_audit = {'status':'NOT_RUN','reason':'TONE_OR_LOCAL_VALIDATION_NOT_READY'}
        final_audit_api = None
        audit_api_records = []
        audit_history = []
        semantic_pass = False

        if self._editorial_ready(final_candidate) and self.cfg.get('facts_only_audit_required',True):
            if self.final_auditor is None:
                raise RuntimeError('FactsOnlySemanticAuditor must be injected by IntegratedPhase3Pipeline')
            safe_facts = self._facts(product, origin_path, content_mode)
            final_text = '\n'.join([
                final_candidate['agent']['body_markdown'],
                final_candidate['agent']['product_title'],
                final_candidate['agent']['seo_title'],
                final_candidate['agent']['meta_description'],
            ])
            final_audit, final_audit_api = self.final_auditor.audit(
                part_number=pn, final_text=final_text, verified_facts=safe_facts, identity=product.get('identity',{})
            )
            audit_api_records.append(final_audit_api)
            audit_history.append({'attempt':1,'result':final_audit,'api':final_audit_api,'artifact_name':final_candidate['artifact_name'],'pdf_access':'CLOSED'})
            semantic_pass = final_audit.get('status') == 'PASS'
            write_json(outdir/'facts_only_final_audit.json', {'result':final_audit,'api':final_audit_api,'history':audit_history,'pdf_access':'CLOSED'})
        elif self._editorial_ready(final_candidate):
            semantic_pass = True
            final_audit = {'status':'SKIPPED_BY_CONFIG'}

        # Freeze patch V1.1: publication is governed by identity/safety/core-structure/
        # tone/factuality. SEO score and numeric density/length targets remain visible
        # quality metrics but cannot by themselves force REVIEW_REQUIRED.
        final_core_ready = self._editorial_ready(final_candidate)
        # Tone API rejection alone must not block a safe pre-tone candidate. Record
        # the rejection for review, but preserve Fact Safety and semantic audit gates.
        publishable = self._publication_ready(final_candidate, tone_pass=True, semantic_pass=semantic_pass)
        if not final_candidate.get('hard_gate_pass'):
            disposition='HARD_GATE_FAILED'; seo_status='HARD_GATE_FAILED'
        elif publishable:
            disposition='PASS'; seo_status='PASS'
        else:
            disposition='REVIEW_REQUIRED'
            if not final_candidate.get('fact_safety_pass'): seo_status='FACT_SAFETY_FAILED'
            elif not self._core_contract_pass(final_candidate): seo_status='STRUCTURE_CONTRACT_FAILED'
            elif not tone_pass and not final_core_ready: seo_status='TONE_REVIEW_REQUIRED'
            else: seo_status='FINAL_SEMANTIC_AUDIT_FAILED'

        final_body = final_candidate['agent']['body_markdown'].strip()+'\n'
        final_html = outdir/'content.html'
        final_html.write_text(render_html(final_body),encoding='utf-8')
        b = final_candidate['bundle']; ag = final_candidate['agent']
        artifacts=[]
        for a in attempts:
            artifacts.append({'attempt':a['attempt'],'artifact_name':a['artifact_name'],'model_tier':a['model_tier'],'model':(a.get('api') or {}).get('model'),
                              'score':a['score'],'hard_gate_pass':a['hard_gate_pass'],'fact_safety_pass':a['fact_safety_pass'],'contract_pass':a['contract_pass'],
                              'generation_mode':a['generation_mode'],
                              'bundle_path':str(a['bundle_path'].relative_to(outdir)).replace('\\','/'),'meta_path':str(a['meta_path'].relative_to(outdir)).replace('\\','/')})

        cost_accounting = self._cost_summary(product, attempts, tone_api_records, audit_api_records)
        scorecard = build_product_scorecard(
            product=product, candidate=final_candidate, tone_record=tone_record, final_audit=final_audit,
            cost_accounting=cost_accounting, writer_expensive_used=expensive_used,
        )
        final = {
            'schema_version':'phase3-altimate-product-v1',
            'identity':product['identity'],
            'source':{**product['source'],'content_mode':content_mode},
            'seo':b['seo'],'page':b['page'],'snippet':{'seo_title':ag['seo_title'],'meta_description':ag['meta_description']},
            'content':{'body_markdown':final_body,'html_path':'content.html','publishing_source':'html','direction':'rtl'},
            'images':b['images'],'links':b['links'],
            'internal_link_policy':{'policy_key':link_selection['policy_key'],'anchor':link_selection['anchor'],'target_url':link_selection['target_url'],'max_occurrences':link_selection['max_occurrences']},
            'woocommerce':{'attributes':ag['woocommerce_attributes']},
            'generation':{
                'agent_version':self.cfg['agent_version'],'prompt_contract_version':self.cfg['prompt_contract_version'],'prompt_sha256':self.prompt_manifest,
                'cheap_writer_model':getattr(self.cheap_agent,'model',None),'expensive_writer_model':None,
                'tone_editor_model':(tone_record.get('api') or {}).get('model') if isinstance(tone_record,dict) else None,
                'cheap_attempts_used':sum(1 for a in attempts if a['model_tier']=='CHEAP'),'fact_safety_repair_attempts_used':fact_safety_repairs_used,'expensive_model_used':expensive_used,
                'escalation_reason':escalation_reason,'attempt_scores':[a['score'] for a in attempts],'selected_artifact':final_candidate['artifact_name'],
                'attempt_artifacts':artifacts,'cost_accounting':cost_accounting,
            },
            'seo_snippet_agent':seo_record,
            'tone_editor':tone_record,
            'validation':{
                'validator_version':self.cfg['validator_version'],'seo_threshold':threshold,'final_seo_score':int(final_candidate['score']),
                'seo_status':seo_status,'disposition':disposition,'publishable':publishable,
                'hard_gates':final_candidate['hard_gates'],'structure_contract':final_candidate['structure'],'fact_safety':final_candidate['fact_safety'],
                'intro_heading':intro_heading_record,
                'style_contract':final_candidate['style_prefilter'],'final_semantic_audit':final_audit,'final_semantic_audit_api':final_audit_api,
                'final_semantic_audit_history':audit_history,
            },
            'evaluation_scorecard':scorecard,
            'publishing':{'target':'woocommerce','status':'NOT_SENT','wordpress_product_id':None,'publish_mode':'DRAFT','description_format':'html','description_path':'content.html','direction':'rtl'},
        }
        validate_json(final, self.root/'schema'/'phase3_final_product.schema.json')
        write_json(final_path, final)
        return {'product':pn,'skipped':False,'score':int(final_candidate['score']),'status':seo_status,'disposition':disposition,'publishable':publishable,
                'final_path':str(final_path),'html_path':str(final_html)}
