import json
from core.category_registry import category_context
from .io_utils import read_json, resolve
from .router import prompt_mode
from .fact_safety import project_safe_facts


def load_prompts(root, content_mode):
    shared=(root/'prompts'/'shared_system.md').read_text(encoding='utf-8')
    mode_file='technical_light.md' if prompt_mode(content_mode)=='TECHNICAL_LIGHT' else 'commercial_only.md'
    mode=(root/'prompts'/mode_file).read_text(encoding='utf-8')
    return shared+'\n\n'+mode


def build_user_payload(input_path, product, content_mode, store_profile, previous=None, validator_feedback=None, link_selection=None, fact_safety_repair=None):
    safe_facts=None
    fp=resolve(input_path, product['source'].get('facts_path'))
    if content_mode=='TECHNICAL_LIGHT':
        if fp is None or not fp.exists():
            raise FileNotFoundError(f'facts_path required for TECHNICAL_LIGHT: {fp}')
        # Altimate V1 boundary: writer sees only FINAL_FACTS; PDF/extraction artifacts are closed.
        safe_facts=project_safe_facts(read_json(fp))
    payload={
      'TARGET_PART_NUMBER':product['identity']['part_number'],
      'CONTENT_MODE':content_mode,
      'CATEGORY_CONTEXT':category_context(product['identity'].get('product_category')),
      'VERIFIED_IDENTITY':product['identity'],
      'ALLOWED_TECHNICAL_FACTS':safe_facts,
      'IMAGES':product.get('images',[]),
      'APPROVED_EXTERNAL_LINKS':product['seo_context'].get('approved_external_links',[]),
      'STORE_PROFILE':store_profile,
      'FACT_COVERAGE': {
          'fact_status': product.get('source',{}).get('fact_status'),
          'useful_fact_count': product.get('source',{}).get('useful_fact_count',0),
          'priority_fact_coverage': product.get('source',{}).get('priority_fact_coverage'),
          'pdf_fallback_used': product.get('source',{}).get('pdf_fallback_used',False),
      },
    }
    if link_selection:
        payload['REQUIRED_INTERNAL_ANCHOR']={
            'phrase':link_selection['anchor'],
            'use_exactly_once_in_body':True,
            'do_not_link_it_yourself':True,
            'url_is_owned_by_deterministic_postprocessor':True,
        }
    if previous is not None:
        payload['PREVIOUS_ATTEMPT']={'score':previous.get('score'),'output':previous.get('agent_output')}
    if validator_feedback is not None:
        payload['VALIDATOR_FEEDBACK_ABSOLUTE']=validator_feedback
    if fact_safety_repair is not None:
        payload['FACT_SAFETY_REPAIR_CONTEXT'] = {
            'ORIGINAL_GENERATED_CONTENT': str(fact_safety_repair.get('original_content') or ''),
            'FACT_SAFETY_ERRORS': fact_safety_repair.get('errors') or [],
            'REPAIR_INSTRUCTION': (
                'Rewrite the prior customer-facing body by correcting every listed fact-safety error. '
                'Use only VERIFIED_IDENTITY and ALLOWED_TECHNICAL_FACTS as technical authority. '
                'Do not add new technical facts or mention the validator/errors to the customer.'
            ),
        }
    return 'INPUT DATA (authoritative):\n'+json.dumps(payload,ensure_ascii=False,indent=2)
