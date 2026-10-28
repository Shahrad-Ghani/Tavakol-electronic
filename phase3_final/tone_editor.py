import json
import os
import re
from pathlib import Path
from phase3_fact_extraction.clients import OpenAITextStructuredAgent


_MD_URL_RE = re.compile(r'(\[[^\]]+\]\()([^\s)]+)(\))')


def _protect_markdown_urls(md: str):
    """Replace URL bytes with immutable placeholders before tone/semantic edits."""
    mapping = {}
    counter = 0
    def repl(m):
        nonlocal counter
        token = f'__TAVAKOL_URL_{counter:03d}__'
        mapping[token] = m.group(2)
        counter += 1
        return m.group(1) + token + m.group(3)
    return _MD_URL_RE.sub(repl, md or ''), mapping


def _restore_markdown_urls(result: dict, mapping: dict):
    out = dict(result or {})
    body = str(out.get('body_markdown') or '')
    for token, url in mapping.items():
        body = body.replace(token, url)
    out['body_markdown'] = body
    return out


class ToneNaturalnessEditor:
    def __init__(self, root, cfg, agent=None):
        self.root = Path(root)
        self.cfg = cfg
        model = os.getenv('TONE_EDITOR_MODEL', cfg['tone_editor_model'])
        self.agent = agent or OpenAITextStructuredAgent(
            model, self.root/'schema'/'tone_editor.schema.json',
            cfg.get('tone_max_output_tokens',6500), cfg.get('tone_reasoning_effort','low'))
        self.instructions = (self.root/'prompts'/'altimate_v1'/'tone_editor.md').read_text(encoding='utf-8')

    def _base_payload(self, *, part_number, body_markdown, verified_facts, store_profile, required_anchor_phrase):
        return {
            'TARGET_PART_NUMBER': part_number,
            'BODY_MARKDOWN': body_markdown,
            'LOCKED_TECHNICAL_FACTS': verified_facts,
            'STORE_PROFILE': store_profile,
            'REQUIRED_INTERNAL_ANCHOR_PHRASE': required_anchor_phrase,
            'ABSOLUTE_RULE': 'Do not add or change technical facts. Edit style only.'
        }

    def _run_with_protected_urls(self, instructions, payload, schema_name):
        protected, mapping = _protect_markdown_urls(payload['BODY_MARKDOWN'])
        payload = dict(payload)
        payload['BODY_MARKDOWN'] = protected
        payload['IMMUTABLE_URL_TOKENS'] = list(mapping.keys())
        payload['URL_RULE'] = 'Do not alter or remove __TAVAKOL_URL_* tokens. They are immutable placeholders.'
        result, api = self.agent.run(instructions, json.dumps(payload, ensure_ascii=False, indent=2), schema_name)
        return _restore_markdown_urls(result, mapping), api

    def edit(self, *, part_number, body_markdown, verified_facts, store_profile, required_anchor_phrase):
        payload = self._base_payload(part_number=part_number, body_markdown=body_markdown, verified_facts=verified_facts,
                                     store_profile=store_profile, required_anchor_phrase=required_anchor_phrase)
        return self._run_with_protected_urls(self.instructions, payload, 'phase3_tone_editor_v52')

    def retry(self, *, part_number, body_markdown, verified_facts, store_profile, required_anchor_phrase, validator_feedback, previous_tone_result):
        payload = self._base_payload(part_number=part_number, body_markdown=body_markdown, verified_facts=verified_facts,
                                     store_profile=store_profile, required_anchor_phrase=required_anchor_phrase)
        payload.update({
            'MODE': 'TARGETED_TONE_RETRY',
            'LOCAL_VALIDATOR_FEEDBACK': validator_feedback,
            'PREVIOUS_TONE_RESULT': previous_tone_result,
            'RETRY_RULE': 'Repair only the listed tone/structure/SEO issues. Do not add sections or facts. Preserve the single FAQ and existing internal link.'
        })
        inst = self.instructions + '\n\nTARGETED RETRY: fix only the supplied validation failures. Do not broaden the edit.'
        return self._run_with_protected_urls(inst, payload, 'phase3_tone_retry_v52')
