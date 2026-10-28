import json
import os
import re
from pathlib import Path


class ContentAgent:
    def __init__(self, model, schema_path, max_output_tokens=6500, body_repair_schema_path=None, reasoning_effort='medium', client=None):
        self.model = model
        self.schema = json.loads(Path(schema_path).read_text(encoding='utf-8'))
        if body_repair_schema_path is None:
            body_repair_schema_path = Path(schema_path).parent / 'body_repair.schema.json'
        self.body_repair_schema = json.loads(Path(body_repair_schema_path).read_text(encoding='utf-8'))
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        if client is None:
            from orchestrator.api_coordinator import CoordinatedOpenAI as OpenAI
            client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        self.client = client

    @staticmethod
    def _parse_json(text):
        text = (text or '').strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S | re.I)
        if m:
            return json.loads(m.group(1))
        a, b = text.find('{'), text.rfind('}')
        if a >= 0 and b > a:
            return json.loads(text[a:b+1])
        raise ValueError('Model did not return parseable JSON')

    def _generate_schema(self, instructions, user_input, schema, schema_name, max_output_tokens=None):
        kwargs = {
            'model': self.model,
            'instructions': instructions,
            'input': user_input,
            'max_output_tokens': max_output_tokens or self.max_output_tokens,
            'reasoning': {'effort': self.reasoning_effort},
            'text': {'format': {'type': 'json_schema', 'name': schema_name, 'schema': schema, 'strict': True}},
        }
        try:
            r = self.client.responses.create(**kwargs)
        except TypeError:
            kwargs.pop('reasoning', None)
            r = self.client.responses.create(**kwargs)
        data = self._parse_json(r.output_text)
        usage = getattr(r, 'usage', None)
        return data, {
            'provider': 'openai', 'model': self.model,
            'response_id': getattr(r, 'id', None),
            'usage': usage.model_dump() if hasattr(usage, 'model_dump') else None,
        }

    def generate(self, instructions, user_input):
        return self._generate_schema(instructions, user_input, self.schema, 'phase3_final_agent_output_v5')

    def repair_body(self, instructions, user_input):
        targeted = instructions + '\n\nReturn only body_markdown in the body-repair schema. Keep every safe passed field unchanged.'
        return self._generate_schema(targeted, user_input, self.body_repair_schema, 'phase3_final_body_repair_v5')
