import hashlib, json, re
from pathlib import Path
from phase3b_validator.markdown_tools import markdown_links
from core.category_registry import category_context, normalize_category_key


def load_policies(root: Path):
    return json.loads((Path(root)/'config'/'internal_links.json').read_text(encoding='utf-8'))


def select_anchor(root: Path, part_number: str, policy_key: str='ic'):
    key = normalize_category_key(policy_key)
    if key:
        ctx = category_context(key)
        anchors = list((ctx.get('internal_link') or {}).get('anchor_variants') or [
            f"خرید {ctx['display_name']}", f"انواع {ctx['display_name']}", f"مشاهده {ctx['display_name']}"
        ])
        p = {'target_url':ctx['category_url'],'anchors':anchors,'required':True,'max_occurrences':1}
        policy_key = key
    else:
        policies=load_policies(root)
        if policy_key not in policies:
            raise KeyError(f'Unknown internal link policy: {policy_key}')
        p=policies[policy_key]
        anchors=list(p['anchors'])
    digest=hashlib.sha256(f'{policy_key}:{part_number}'.encode('utf-8')).digest()
    idx=int.from_bytes(digest[:8],'big') % len(anchors)
    return {'policy_key':policy_key,'anchor':anchors[idx],'target_url':p['target_url'],'allowed_anchors':anchors,'required':bool(p.get('required',True)),'max_occurrences':int(p.get('max_occurrences',1))}


def _de_link_policy_anchors(md: str, allowed_anchors):
    """Remove any model-owned policy link before deterministic injection.

    Altimate V1 also repairs malformed nested Markdown such as ``[[anchor](url)]``
    observed in the prior live regression. Only the approved anchor phrase is
    retained; the URL is always re-injected from config.
    """
    for a in allowed_anchors:
        esc = re.escape(a)
        md = re.sub(r'\[\s*\[' + esc + r'\]\([^)]*\)\s*\]', a, md, flags=re.I)
        md = re.sub(r'\[' + esc + r'\]\([^)]*\)', a, md, flags=re.I)
        md = re.sub(r'<a\s+[^>]*href=["\'][^"\']+["\'][^>]*>\s*' + esc + r'\s*</a>', a, md, flags=re.I)
    return md


def inject_policy_link(md: str, selection: dict):
    anchor=selection['anchor']; url=selection['target_url']
    md=_de_link_policy_anchors(md, selection['allowed_anchors'])
    # Remove duplicate bare occurrences beyond the first selected anchor only by leaving text intact;
    # contract validator will flag >1. We only take ownership of link URL here.
    linked=f'[{anchor}]({url})'
    lines=md.splitlines()
    injected=False
    # Prefer an ordinary paragraph line already containing the selected phrase.
    for i,line in enumerate(lines):
        st=line.strip()
        if not st or st.startswith('#') or st.startswith('|') or st in {'---','***','___'}:
            continue
        if anchor in line:
            lines[i]=line.replace(anchor,linked,1)
            injected=True
            break
    if not injected:
        fallback=f'برای مشاهده مدل‌های بیشتر و مقایسه گزینه‌های موجود، {linked} را بررسی کنید.'
        # Put it near the beginning, before the first main separator when possible.
        insert_at=None
        for i,line in enumerate(lines):
            if line.strip()=='---':
                insert_at=i
                break
        if insert_at is None:
            lines.extend(['',fallback])
        else:
            lines[insert_at:insert_at]=['',fallback,'']
        injected=True
    out='\n'.join(lines).strip()+'\n'
    links=[x for x in markdown_links(out) if x.get('url')==url and x.get('text')==anchor]
    return out, {'anchor':anchor,'target_url':url,'injected':injected,'exact_policy_links_found':len(links)}


def audit_policy_link(md: str, selection: dict):
    """Audit only; never mutates content. Used after Tone Editor in Altimate V1."""
    anchor = selection['anchor']; url = selection['target_url']
    links = [x for x in markdown_links(md or '') if x.get('url') == url and x.get('text') == anchor]
    return {
        'anchor': anchor,
        'target_url': url,
        'injected': False,
        'audit_only': True,
        'exact_policy_links_found': len(links),
    }
