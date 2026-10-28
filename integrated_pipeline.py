import shutil
import unicodedata
from pathlib import Path

from dotenv import load_dotenv

from phase3_final.io_utils import read_json, write_json
from phase3_final.schemas import validate_json
from phase3_final.pipeline import Phase3FinalPipeline
from phase3_final.final_auditor import FactsOnlySemanticAuditor
from phase3_fact_extraction.pipeline import FactExtractionPipeline, extract_verified_package
from phase3_fact_extraction.clients import OpenAIFileManager
from core.category_registry import category_context

_PHASE3_LOG_SINK = None

def set_phase3_log_sink(callback):
    global _PHASE3_LOG_SINK
    _PHASE3_LOG_SINK = callback

def phase3_log(message):
    text = ' '.join(str(message).replace('\r',' ').replace('\n',' ').split())
    print(text, flush=True)
    if _PHASE3_LOG_SINK:
        try:
            _PHASE3_LOG_SINK(text)
        except Exception:
            pass


class PipelineStageError(RuntimeError):
    def __init__(self, stage, original):
        self.stage = stage
        self.original = original
        super().__init__(f'[{stage}] {original}')


def _safe_name(text):
    s = unicodedata.normalize('NFKC', text or '').strip().casefold()
    return s.replace('–','-').replace('—','-').replace('−','-')


def find_exact_datasheet(datasheets_dir, part_number):
    datasheets_dir = Path(datasheets_dir)
    target = _safe_name(part_number)
    matches = [p for p in datasheets_dir.glob('*.pdf') if _safe_name(p.stem) == target]
    matches += [p for p in datasheets_dir.glob('*.PDF') if _safe_name(p.stem) == target and p not in matches]
    if len(matches) > 1:
        raise RuntimeError(f'Multiple exact datasheet files found for {part_number}')
    return matches[0].resolve() if matches else None


class IntegratedPhase3Pipeline:
    def __init__(self, root, fact_extractor=None, content_pipeline=None, file_manager=None, final_auditor=None):
        load_dotenv()
        self.root = Path(root).resolve()
        self.cfg = read_json(self.root/'config'/'phase3_final.json')
        self.file_manager = file_manager or OpenAIFileManager()
        self.fact_extractor = fact_extractor or FactExtractionPipeline(self.root, self.cfg, file_manager=self.file_manager)
        self.final_auditor = final_auditor or FactsOnlySemanticAuditor(self.root, self.cfg, client=self.file_manager.client)
        self.content = content_pipeline or Phase3FinalPipeline(self.root, final_auditor=self.final_auditor)

    def _enrich(self, input_path, product, datasheets_dir, force_fact_extraction=False):
        pn = product['identity']['part_number']
        hint = product.get('source_hint') or {}
        hinted_pdf = hint.get('datasheet_path')
        pdf = None
        if hinted_pdf and hint.get('phase2_verified_exact_match'):
            candidate = Path(hinted_pdf)
            if not candidate.is_absolute():
                candidate = (self.root / candidate).resolve()
            if candidate.exists() and candidate.is_file():
                pdf = candidate
        if pdf is None:
            pdf = find_exact_datasheet(datasheets_dir, pn)
        identity = dict(product['identity'])
        if pdf is None:
            source = {
                'datasheet_status':'NO_FULL_DATASHEET',
                'datasheet_path':None,
                'model_pdf_path':None,
                'pdf_window':None,
                'source_validation':'NO_FILE',
                'fact_status':'NOT_RUN',
                'useful_fact_count':0,
                'facts_path':None,
                'primary_extraction_path':None,
                'fallback_extraction_path':None,
                'coverage_path':None,
                'pdf_calls':0,
                'pdf_fallback_used':False,
                'priority_fact_coverage':None,
            }
            return {**product,'identity':identity,'source':source}

        work = self.root/'work'/'fact_extraction'/pn
        max_pages = int(self.cfg.get('pdf_first_pages',5))
        phase3_log(f'[{pn}] Fact extraction | first_pages={max_pages} | status=START')
        result = self.fact_extractor.process(pn, pdf, work, force=force_fact_extraction, priority_categories=category_context(product['identity'].get('product_category') or 'ic').get('technical_focus'))
        sv, facts, cov = result['source_validation'], result['facts'], result['coverage']
        window = result.get('pdf_window') or {}
        phase3_log(
            f"[{pn}] PDF facts complete | pages={window.get('pages_sent_to_models')}/{window.get('original_pages')} "
            f"| pdf_calls={sv.get('pdf_calls')} | fallback={sv.get('fallback_used')} "
            f"| facts={facts.get('useful_fact_count',0)} | priority={cov.get('priority_count')}/{cov.get('priority_total')} "
            f"| coverage={'OK' if cov.get('sufficient') else 'SPARSE'}"
        )

        exact_ok = bool(sv.get('exact_part_number_found')) and sv.get('source_kind') == 'DATASHEET'
        if identity.get('manufacturer') is None and exact_ok and sv.get('manufacturer'):
            identity['manufacturer'] = sv['manufacturer']
        verified_pkg = extract_verified_package(facts) if exact_ok else None
        if not identity.get('verified_package_installation') and verified_pkg:
            identity['verified_package_installation'] = verified_pkg

        useful = int(facts.get('useful_fact_count') or 0) if exact_ok else 0
        source = {
            'datasheet_status':'FULL_DATASHEET' if exact_ok else 'NO_FULL_DATASHEET',
            'datasheet_path':str(pdf),
            'model_pdf_path':str(Path(result['model_pdf_path']).resolve()),
            'pdf_window':window,
            'source_validation':'EXACT_DATASHEET_CONFIRMED' if exact_ok else 'IDENTITY_NOT_CONFIRMED',
            'fact_status':facts.get('fact_status','NOT_RUN') if exact_ok else 'NOT_RUN',
            'useful_fact_count':useful,
            'facts_path':str(Path(result['facts_path']).resolve()) if exact_ok and useful > 0 else None,
            'primary_extraction_path':str(Path(result['primary_path']).resolve()),
            'fallback_extraction_path':str(Path(result['fallback_path']).resolve()) if result.get('fallback_path') else None,
            'coverage_path':str(Path(result['coverage_path']).resolve()),
            'pdf_calls':int(sv.get('pdf_calls') or 0),
            'pdf_fallback_used':bool(sv.get('fallback_used')),
            'priority_fact_coverage':cov,
        }
        return {**product,'identity':identity,'source':source}

    def process(self, input_path, datasheets_dir, outputs_dir, force=False, force_fact_extraction=False):
        input_path = Path(input_path).resolve()
        outputs_dir = Path(outputs_dir).resolve()
        outputs_dir.mkdir(parents=True, exist_ok=True)
        try:
            product = read_json(input_path)
            validate_json(product, self.root/'schema'/'product_input.schema.json')
        except Exception as e:
            raise PipelineStageError('INPUT_VALIDATION', e) from e

        try:
            enriched = self._enrich(input_path, product, datasheets_dir, force_fact_extraction=force_fact_extraction)
        except Exception as e:
            self.file_manager.cleanup()
            raise PipelineStageError('FACT_EXTRACTION', e) from e

        pn = enriched['identity']['part_number']
        internal_root = self.root/'work'/'content'
        try:
            phase3_log(f'[{pn}] Content pipeline Altimate V1.2 | status=START')
            result = self.content.process_product(enriched, input_path, internal_root, force=bool(force or force_fact_extraction))
            state = read_json(result['final_path'])
            intro = (state.get('validation') or {}).get('intro_heading') or {}
            if intro:
                action = 'INSERTED' if intro.get('programmatic_repair_applied') else 'PRESENT'
                phase3_log(
                    f"[{pn}] Intro header | status={action} | expected={intro.get('expected')}"
                )
            internal_html = Path(result['html_path'])
        except Exception as e:
            raise PipelineStageError('CONTENT_PIPELINE', e) from e
        finally:
            # PDF is closed after fact extraction. Uploaded model window is deleted.
            self.file_manager.cleanup()

        out_html = outputs_dir/f'{pn}.html'
        out_json = outputs_dir/f'{pn}.json'
        try:
            shutil.copy2(internal_html, out_html)
            state['content']['html_path'] = out_html.name
            if isinstance(state.get('publishing'), dict):
                state['publishing']['description_path'] = out_html.name
            for key in (
                'datasheet_path','model_pdf_path','facts_path','primary_extraction_path',
                'fallback_extraction_path','coverage_path'
            ):
                value = state['source'].get(key)
                if value:
                    try:
                        state['source'][key] = str(Path(value).resolve().relative_to(self.root)).replace('\\','/')
                    except Exception:
                        pass
            validate_json(state, self.root/'schema'/'phase3_final_product.schema.json')
            write_json(out_json, state)
        except Exception as e:
            raise PipelineStageError('OUTPUT_EXPORT', e) from e

        return {
            'product':pn,
            'score':int(state['validation']['final_seo_score']),
            'status':state['validation']['seo_status'],
            'disposition':state['validation']['disposition'],
            'publishable':bool(state['validation']['publishable']),
            'estimated_cost_usd':state.get('generation',{}).get('cost_accounting',{}).get('estimated_total_cost_usd',0.0),
            'scorecard':state.get('evaluation_scorecard',{}),
            'json':out_json,'html':out_html,
        }
