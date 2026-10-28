"""Conservative MOSFET attribute resolver for Integrated V4.0.5.

Consumes previously grounded structured facts (datasheet / verified distributors).
Never substitutes pulsed drain current, on-state test ID, or JFET IDSS for
continuous drain current. Returns unavailable fields for manual review.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _spec(value=None, *, source=None, fact_id=None, status='UNRESOLVED'):
    return {'value': value, 'status': status, 'source': source, 'fact_id': fact_id}


def _number_unit(text: str, preferred_unit: str | None = None) -> str | None:
    # Disallow 'typ' and 'max' qualifiers leaking into a WooCommerce attribute.
    matched = re.search(r'(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*(mA|µA|uA|A|kV|V)\b', text, re.I)
    if matched:
        return f'{matched.group(1)} {matched.group(2)}'
    if preferred_unit:
        matched = re.search(r'(?<![\w.])([-+]?\d+(?:\.\d+)?)\b', text)
        if matched:
            return f'{matched.group(1)} {preferred_unit}'
    return None


def extract_mosfet_specs(facts: dict[str, Any], *, source: str = 'DATASHEET_FACTS') -> dict[str, Any]:
    """Return channel_type, vds, id_continuous + missing; never invent numbers."""
    result: dict[str, Any] = {k: _spec() for k in ('channel_type', 'vds', 'id_continuous')}
    records = [v for field in ('seo_ready_facts', 'limit_only_facts')
               for v in (facts.get(field) or []) if isinstance(v, dict)]
    for fact in records:
        parameter = str(fact.get('parameter') or '')
        claim = str(fact.get('claim') or '')
        value = str(fact.get('value_text') or '')
        full = f'{parameter} {claim} {value}'
        low = full.lower()
        fact_id = fact.get('id')
        if result['channel_type']['value'] is None and (('channel' in low) or ('transistor type' in low) or ('device type' in low) or ('device function' in low)):
            # Explicit statements only. Enhancement mode is not a channel type.
            match = re.search(r'\b([np])\s*[- ]\s*channel\b', full, re.I)
            if match:
                result['channel_type'] = _spec(match.group(1).upper()+'-Channel', source=source, fact_id=fact_id, status='RESOLVED')
        if result['vds']['value'] is None and re.search(r'(?:drain[\s-]*(?:to[\s-]*)?source|\bvds\b)', parameter, re.I) and (
                'breakdown' in low or 'maximum' in low or 'voltage rating' in low or 'voltage' in low):
            # Prefer parameter-specific value before entire claim (which may mention test conditions).
            num = _number_unit(value, fact.get('unit') or 'V')
            if num and num.lower().endswith((' v', ' kv')):
                result['vds'] = _spec(num, source=source, fact_id=fact_id, status='RESOLVED')
        if result['id_continuous']['value'] is None:
            # Require unambiguous CONTINUOUS ID. On-state drain and pulsed current are different ratings.
            if re.search(r'(?:continuous\s+drain\s+current|drain\s+current\s*\(?continuous\)?|\bid\s+continuous\b)', full, re.I):
                match = re.search(r'(?:continuous\s+drain\s+current|drain\s+current\s*\(?continuous\)?|\bid\s+continuous\b)\s*(?:is|:|=)?\s*([-+]?\d+(?:\.\d+)?)\s*(mA|µA|uA|A)\b', full, re.I)
                if match:
                    result['id_continuous'] = _spec(f'{match.group(1)} {match.group(2)}', source=source, fact_id=fact_id, status='RESOLVED')
                elif 'pulsed' not in low and ('continuous' in parameter.lower()):
                    num = _number_unit(value, fact.get('unit'))
                    if num and num.lower().endswith((' a', ' ma', ' µa', ' ua')):
                        result['id_continuous'] = _spec(num, source=source, fact_id=fact_id, status='RESOLVED')
    result['missing'] = [k for k in ('channel_type','vds','id_continuous') if result[k]['value'] is None]
    return result


def resolve_for_product(root: Path, part_number: str, category_key: str) -> dict[str, Any]:
    if category_key != 'mosfet':
        return {}
    root = Path(root)
    path = root / 'work' / 'fact_extraction' / part_number / 'final_facts.json'
    if not path.exists():
        return extract_mosfet_specs({})
    try:
        facts = json.loads(path.read_text(encoding='utf-8'))
        if str(facts.get('part_number','')).casefold() != part_number.casefold():
            raise ValueError('Facts belong to another part number')
        return extract_mosfet_specs(facts)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return extract_mosfet_specs({})
