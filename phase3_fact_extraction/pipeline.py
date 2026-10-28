import json
import os
from pathlib import Path

from phase3_final.io_utils import write_json, read_json
from phase3_final.schemas import validate_json
from .clients import OpenAIPdfStructuredAgent, OpenAIFileManager
from .pdf_window import build_pdf_window
from .coverage import build_coverage
from core.package_resolution import clean_package

FAMILY_SENSITIVE = ('package', 'pin count', 'pinout', 'package dimensions', 'ordering code', 'order code', 'number of pins', 'pins')


def _family_sensitive(parameter):
    p = (parameter or '').strip().casefold()
    return any(x in p for x in FAMILY_SENSITIVE)


def _fact_key(f):
    return tuple(str(f.get(k) or '').strip().casefold() for k in ('parameter','value_text','unit','condition','section'))


def apply_extraction_policy(candidates, max_facts=16):
    """Conservative local policy applied after the single model extraction call.

    This is not a second semantic verifier. It only enforces immutable safety
    rules that are deterministic from the structured model output.
    """
    accepted, limits, rejected, seen = [], [], [], set()
    for raw in list(candidates or [])[:max_facts]:
        fact = {k: raw.get(k) for k in ('id','parameter','claim','value_text','unit','condition','section','scope','seo_usage','page')}
        if fact.get('section') == 'ABSOLUTE_MAXIMUM':
            fact['seo_usage'] = 'LIMIT_ONLY'
        if _family_sensitive(fact.get('parameter')) and fact.get('scope') != 'TARGET_ONLY':
            rejected.append({'id':fact.get('id'),'reason':'FAMILY_SENSITIVE_NOT_TARGET_ONLY'})
            continue
        if fact.get('seo_usage') == 'NEVER':
            rejected.append({'id':fact.get('id'),'reason':'SEO_USAGE_NEVER'})
            continue
        key = _fact_key(fact)
        if key in seen:
            rejected.append({'id':fact.get('id'),'reason':'DUPLICATE_FACT'})
            continue
        seen.add(key)
        if fact.get('seo_usage') == 'LIMIT_ONLY':
            limits.append(fact)
        else:
            accepted.append(fact)
    n = len(accepted) + len(limits)
    status = 'SUFFICIENT' if n >= 6 else 'THIN' if n >= 3 else 'INSUFFICIENT' if n > 0 else 'NOT_RUN'
    return {
        'fact_status': status,
        'seo_ready_facts': accepted,
        'limit_only_facts': limits,
        'useful_fact_count': n,
        'rejected': rejected,
    }


def extract_verified_package(facts):
    for fact in (facts or {}).get('seo_ready_facts', []):
        if fact.get('section') == 'PACKAGE' and fact.get('scope') == 'TARGET_ONLY':
            val = clean_package(fact.get('value_text')) or clean_package(fact.get('claim'))
            if val:
                return val
    return None


class FactExtractionPipeline:
    """Cost-controlled Phase 3 PDF stage.

    Integrated V2.1 invariant: exactly one GPT-5.6 Luna PDF call per technical
    product. Sparse coverage is reported to downstream validators; it never
    triggers a second PDF model call.
    """
    def __init__(self, root, cfg, primary_agent=None, fallback_agent=None, file_manager=None):
        self.root = Path(root)
        self.cfg = cfg
        self.file_manager = file_manager or OpenAIFileManager()
        schema = self.root/'schema'/'fact_extraction.schema.json'
        primary_model = os.getenv('PDF_PRIMARY_MODEL', cfg['pdf_primary_model'])
        self.primary = primary_agent or OpenAIPdfStructuredAgent(
            primary_model, schema, self.file_manager,
            cfg.get('pdf_max_output_tokens',6500), cfg.get('pdf_reasoning_effort','medium'))
        self.fallback = None  # V2.1: second PDF-model call intentionally disabled

    def _run(self, agent, pdf_path, instructions, target_part_number, pdf_window, mode, primary_result=None, coverage=None, priority_categories=None):
        payload = {
            'TARGET_PART_NUMBER': target_part_number,
            'PDF_WINDOW': pdf_window,
            'MODE': mode,
            'PRIORITY_FACT_CATEGORIES': list(priority_categories or self.cfg.get('fact_coverage',{}).get('priority_categories',[])),
            'IMPORTANT_CLARIFICATION': 'Priority categories are hints for useful coverage, NOT a whitelist. Extract any other directly supported SEO-useful facts too.',
        }
        if primary_result is not None:
            payload['PRIMARY_EXTRACTION'] = primary_result
            payload['PRIMARY_COVERAGE'] = coverage or {}
            payload['FALLBACK_RULE'] = 'Re-read the PDF independently. Return a single consolidated fact set: keep supported useful facts, correct omissions, and add missing useful facts when directly visible. Do not force any priority fact that the PDF window does not support.'
        return agent.run(pdf_path, instructions, json.dumps(payload, ensure_ascii=False, indent=2), f'phase3_fact_extraction_{mode.lower()}_v1')

    def process(self, part_number, pdf_path, work_dir, force=False, priority_categories=None):
        pdf_path = Path(pdf_path).resolve()
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        primary_path = work_dir/'primary_extraction.json'
        fallback_path = work_dir/'fallback_extraction.json'
        facts_path = work_dir/'final_facts.json'
        coverage_path = work_dir/'coverage.json'
        source_path = work_dir/'source_validation.json'
        model_pdf_path = work_dir/'datasheet_first5.pdf'
        window_path = work_dir/'pdf_window.json'

        required_cache = (primary_path, facts_path, coverage_path, source_path, model_pdf_path, window_path)
        if all(x.exists() for x in required_cache) and not force:
            return {
                'primary_path': primary_path,
                'fallback_path': fallback_path if fallback_path.exists() else None,
                'facts_path': facts_path,
                'coverage_path': coverage_path,
                'source_validation': read_json(source_path),
                'facts': read_json(facts_path),
                'coverage': read_json(coverage_path),
                'cached': True,
                'model_pdf_path': model_pdf_path,
                'pdf_window': read_json(window_path),
            }

        max_pages = int(self.cfg.get('pdf_first_pages',5))
        pdf_window = build_pdf_window(pdf_path, model_pdf_path, max_pages=max_pages)
        write_json(window_path, pdf_window)

        primary_prompt = (self.root/'prompts'/'altimate_v1'/'fact_extractor_primary.md').read_text(encoding='utf-8')
        primary_obj, primary_api = self._run(self.primary, model_pdf_path, primary_prompt, part_number, pdf_window, 'PRIMARY', priority_categories=priority_categories)
        validate_json(primary_obj, self.root/'schema'/'fact_extraction.schema.json')
        primary_policy = apply_extraction_policy(primary_obj.get('facts',[]), int(self.cfg.get('fact_extraction_max_facts',16)))
        primary_coverage = build_coverage(primary_policy, self.cfg, exact_part_number_covered=bool(primary_obj['source_assessment'].get('exact_part_number_covered')))
        write_json(primary_path, {'result':primary_obj,'policy':primary_policy,'coverage':primary_coverage,'api':primary_api,'pdf_window':pdf_window})

        final_obj, final_api, final_policy, fallback_used = primary_obj, primary_api, primary_policy, False
        final_coverage = primary_coverage

        # V2.1 cost rule: never buy a second PDF-model pass. If the first five
        # pages do not provide enough evidence, preserve the safe Luna facts and
        # mark coverage as sparse/identity-not-confirmed for downstream review.

        source_assessment = final_obj['source_assessment']
        source = {
            'exact_part_number_found': bool(source_assessment.get('exact_part_number_covered')),
            'source_kind': source_assessment.get('source_kind','OTHER'),
            'manufacturer': source_assessment.get('manufacturer'),
            'reason': source_assessment.get('reason',''),
            'original_source_status': 'EXACT_DATASHEET_FILE_RESOLVED_BY_PHASE2',
            'model_window_truncated': bool(pdf_window.get('truncated')),
            'pdf_window': pdf_window,
            'primary_model': primary_api.get('model'),
            'fallback_model': None,
            'fallback_used': fallback_used,
            'pdf_calls': 1,
        }
        write_json(source_path, source)

        facts = {
            'schema_version':'phase3-final-facts-v1',
            'part_number':part_number,
            'source_status':'EXACT_DATASHEET' if source['exact_part_number_found'] else 'IDENTITY_NOT_CONFIRMED',
            'fact_status':final_policy['fact_status'],
            'seo_ready_facts':final_policy['seo_ready_facts'],
            'limit_only_facts':final_policy['limit_only_facts'],
            'useful_fact_count':final_policy['useful_fact_count'],
            'coverage':final_coverage,
            'extraction':{
                'primary_model':primary_api.get('model'),
                'fallback_used':fallback_used,
                'fallback_model':None,
                'pdf_calls':1,
                'pdf_closed_after_stage':True,
            },
            'audit':{'rejected':final_policy['rejected']},
        }
        write_json(facts_path, facts)
        write_json(coverage_path, final_coverage)
        return {
            'primary_path':primary_path,
            'fallback_path':fallback_path if fallback_used else None,
            'facts_path':facts_path,
            'coverage_path':coverage_path,
            'source_validation':source,
            'facts':facts,
            'coverage':final_coverage,
            'cached':False,
            'model_pdf_path':model_pdf_path,
            'pdf_window':pdf_window,
        }
