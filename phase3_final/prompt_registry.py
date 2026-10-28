import hashlib
from pathlib import Path

PROMPT_FILES = [
    'prompts/shared_system.md',
    'prompts/technical_light.md',
    'prompts/commercial_only.md',
    'prompts/retry.md',
    'prompts/fact_safety_retry.md',
    'prompts/seo_snippet.md',
    'prompts/altimate_v1/fact_extractor_primary.md',
    'prompts/altimate_v1/fact_extractor_fallback.md',
    'prompts/altimate_v1/tone_editor.md',
    'prompts/altimate_v1/facts_only_auditor.md',
]


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_prompt_manifest(root):
    root = Path(root)
    return {p: sha256_file(root/p) for p in PROMPT_FILES}
