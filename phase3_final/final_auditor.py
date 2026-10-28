import json
import os
from pathlib import Path
from phase3_fact_extraction.clients import OpenAITextStructuredAgent


class FactsOnlySemanticAuditor:
    """Final semantic gate. It never receives a PDF.

    The PDF stage is closed after FINAL_FACTS is produced; this auditor only
    checks that customer content does not exceed or corrupt those facts.
    """
    def __init__(self, root, cfg, agent=None, client=None):
        self.root = Path(root)
        self.cfg = cfg
        model = os.getenv('FACTS_AUDITOR_MODEL', cfg['facts_auditor_model'])
        schema = self.root/'schema'/'final_semantic_audit.schema.json'
        self.agent = agent or OpenAITextStructuredAgent(
            model, schema, cfg.get('audit_max_output_tokens',3200),
            cfg.get('auditor_reasoning_effort','low'), client=client)
        self.instructions = (self.root/'prompts'/'altimate_v1'/'facts_only_auditor.md').read_text(encoding='utf-8')

    def audit(self, *, part_number, final_text, verified_facts, identity):
        payload = json.dumps({
            'TARGET_PART_NUMBER': part_number,
            'VERIFIED_IDENTITY': identity,
            'FINAL_FACTS': verified_facts,
            'FINAL_CUSTOMER_CONTENT': final_text,
            'PDF_ACCESS': 'CLOSED',
        }, ensure_ascii=False, indent=2)
        return self.agent.run(self.instructions, payload, 'phase3_facts_only_final_audit_v1')

# Compatibility alias for older imports; implementation is facts-only.
FinalSemanticAuditor = FactsOnlySemanticAuditor
