"""V4.0.5: local-only category editor; never mutates WordPress taxonomy.

An inactive definition stays resolvable so historical approved bundles and metadata
retain their immutable category meaning. Only active definitions appear in the UI.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from core.category_registry import REGISTRY_PATH, load_registry


class CategoryAlreadyExists(ValueError):
    pass


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(s or "")).replace("\u200c", " ").strip()).casefold()


def _write_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)
    load_registry.cache_clear()


def active_categories() -> dict[str, dict[str, Any]]:
    return {k:v for k,v in load_registry()['categories'].items() if v.get('active', True)}


def add_category(*, display_name: str, parent: str, wordpress_child: str,
                 title_prefix: str, category_url: str, density_phrase: str = '',
                 wordpress_term_id: int | str | None = None,
                 registry_path: Path | None = None) -> str:
    """Add a software category mapped to an *existing* WP term.

    A missing child term ID is resolved safely from the live WordPress category tree
    at publication time. No registration action is sent to WordPress.
    """
    path = Path(registry_path or REGISTRY_PATH)
    if not all(str(x or '').strip() for x in (display_name,parent,wordpress_child,title_prefix,category_url)):
        raise ValueError('All category mapping fields are required')
    if not category_url.strip().startswith(('https://','http://')):
        raise ValueError('Internal category link must start with https:// or http://')
    registry = json.loads(path.read_text(encoding='utf-8'))
    cats = registry['categories']
    all_parents = {v['wordpress']['parent']: v['wordpress']['parent_term_id'] for v in cats.values()}
    if parent not in all_parents:
        raise ValueError('Parent must be an existing WordPress category parent')
    for key, rec in cats.items():
        if _norm(rec.get('display_name')) == _norm(display_name) or (
            _norm(rec.get('wordpress',{}).get('parent')) == _norm(parent)
            and _norm(rec.get('wordpress',{}).get('child')) == _norm(wordpress_child)
        ):
            raise CategoryAlreadyExists('Category already exists')
    normalized_english = re.sub(r'[^a-z0-9]+', '_', display_name.lower()).strip('_')
    key = normalized_english if normalized_english else 'custom_' + hashlib.sha1((parent+'|'+display_name).encode('utf-8')).hexdigest()[:10]
    if key in cats:
        key += '_' + hashlib.sha1((parent+'|'+wordpress_child).encode('utf-8')).hexdigest()[:5]
    term_id = int(wordpress_term_id or 0)
    if term_id < 0:
        raise ValueError('WordPress term id must be positive or blank')
    cats[key] = {
        'display_name': display_name.strip(),
        'title_prefix': title_prefix.strip(),
        'density_phrase': density_phrase.strip() or ('این ' + display_name.strip()),
        'slug_rule': '{pn}-' + key.replace('_','-'),
        'wordpress': {'parent': parent, 'parent_term_id': all_parents[parent],
                      'child': wordpress_child.strip(), 'term_id': term_id},
        'category_url': category_url.strip(),
        'technical_focus': ['Part Number', 'Package'],
        'custom': True, 'active': True,
    }
    _write_registry(path, registry)
    return key


def remove_category(key: str, *, registry_path: Path | None = None) -> None:
    path = Path(registry_path or REGISTRY_PATH)
    registry = json.loads(path.read_text(encoding='utf-8'))
    rec = registry['categories'].get(key)
    if rec is None:
        raise KeyError(f'Category {key!r} does not exist')
    if not rec.get('custom'):
        raise ValueError('Built-in category cannot be removed')
    # Soft-delete protects metadata and already approved bundles.
    rec['active'] = False
    _write_registry(path, registry)
