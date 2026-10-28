import json
import os
import re
from pathlib import Path


def parse_json_text(text):
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


class OpenAIFileManager:
    """Per-process upload cache for the single 5-page PDF extraction call."""
    def __init__(self, client=None):
        if client is None:
            from orchestrator.api_coordinator import CoordinatedOpenAI as OpenAI
            client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        self.client = client
        self._cache = {}

    def get_file_id(self, pdf_path):
        key = str(Path(pdf_path).resolve())
        if key not in self._cache:
            with open(key, 'rb') as f:
                obj = self.client.files.create(file=f, purpose='user_data')
            self._cache[key] = obj.id
        return self._cache[key]

    def cleanup(self, pdf_path=None):
        keys = [str(Path(pdf_path).resolve())] if pdf_path else list(self._cache)
        for key in keys:
            fid = self._cache.pop(key, None)
            if fid:
                try:
                    self.client.files.delete(fid)
                except Exception:
                    pass


class OpenAIPdfStructuredAgent:
    def __init__(self, model, schema_path, file_manager, max_output_tokens=6500, reasoning_effort='medium'):
        self.model = model
        self.schema = json.loads(Path(schema_path).read_text(encoding='utf-8'))
        self.file_manager = file_manager
        self.client = file_manager.client
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort

    def run(self, pdf_path, instructions, payload, schema_name):
        fid = self.file_manager.get_file_id(pdf_path)
        kwargs = {
            'model': self.model,
            'instructions': instructions,
            'input': [{
                'role': 'user',
                'content': [
                    {'type': 'input_file', 'file_id': fid, 'detail': 'auto'},
                    {'type': 'input_text', 'text': payload},
                ],
            }],
            'max_output_tokens': self.max_output_tokens,
            'reasoning': {'effort': self.reasoning_effort},
            'text': {'format': {'type': 'json_schema', 'name': schema_name, 'schema': self.schema, 'strict': True}},
        }
        try:
            r = self.client.responses.create(**kwargs)
        except TypeError:
            kwargs.pop('reasoning', None)
            r = self.client.responses.create(**kwargs)
        data = parse_json_text(r.output_text)
        usage = getattr(r, 'usage', None)
        return data, {
            'provider':'openai','model':self.model,'response_id':getattr(r,'id',None),
            'usage':usage.model_dump() if hasattr(usage,'model_dump') else None,
        }


class OpenAITextStructuredAgent:
    def __init__(self, model, schema_path, max_output_tokens=6500, reasoning_effort='low', client=None):
        self.model = model
        self.schema = json.loads(Path(schema_path).read_text(encoding='utf-8'))
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        if client is None:
            from orchestrator.api_coordinator import CoordinatedOpenAI as OpenAI
            client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        self.client = client

    def run(self, instructions, payload, schema_name):
        kwargs = {
            'model': self.model,
            'instructions': instructions,
            'input': payload,
            'max_output_tokens': self.max_output_tokens,
            'reasoning': {'effort': self.reasoning_effort},
            'text': {'format': {'type': 'json_schema', 'name': schema_name, 'schema': self.schema, 'strict': True}},
        }
        try:
            r = self.client.responses.create(**kwargs)
        except TypeError:
            kwargs.pop('reasoning', None)
            r = self.client.responses.create(**kwargs)
        data = parse_json_text(r.output_text)
        usage = getattr(r, 'usage', None)
        return data, {
            'provider':'openai','model':self.model,'response_id':getattr(r,'id',None),
            'usage':usage.model_dump() if hasattr(usage,'model_dump') else None,
        }
