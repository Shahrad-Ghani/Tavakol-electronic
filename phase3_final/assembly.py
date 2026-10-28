from core.category_registry import product_title, product_slug
import re


def slugify_part_number(pn):
    s=pn.casefold().strip().replace('_','-')
    s=re.sub(r'\s+','-',s); s=re.sub(r'-+','-',s)
    return s.strip('-/')


def _allowed_map(items): return {x['url']:x for x in items}


def sanitize_agent_output(product, agent):
    pn=product['identity']['part_number']
    out=dict(agent)
    # V3.0: Product title is not an LLM field. It is deterministic and exact.
    out['product_title']=product_title(pn, product['identity'].get('product_category'))
    out.setdefault('woocommerce_attributes',{})['part_number']=pn
    verified=product['identity'].get('verified_package_installation')
    out['woocommerce_attributes']['package_installation']=verified or 'نیازمند تأیید'

    # Internal category-link URL is owned by deterministic post-processing in V1.
    # Any model-declared internal URLs are ignored here.
    out['internal_links']=[]

    allowed_e=_allowed_map(product['seo_context'].get('approved_external_links',[]))
    out['external_links']=[x for x in out.get('external_links',[]) if x.get('url') in allowed_e]

    altmap={x.get('filename'):x.get('alt','') for x in out.get('image_alts',[])}
    image_alts=[]
    for img in product.get('images',[]):
        alt=altmap.get(img['filename'],'')
        if img.get('is_primary') and pn.casefold() not in alt.casefold():
            alt=f"{product['identity'].get('product_type_label') or 'محصول'} {pn}"
        image_alts.append({'filename':img['filename'],'alt':alt})
    out['image_alts']=image_alts
    return out


def build_attempt_bundle(product, content_mode, agent, body_markdown, attempt, generator_version):
    pn=product['identity']['part_number']
    altmap={x['filename']:x['alt'] for x in agent.get('image_alts',[])}
    images=[]
    for img in product.get('images',[]):
        images.append({'filename':img['filename'],'path':img.get('path'),'alt':altmap.get(img['filename'],''),'is_primary':img.get('is_primary',False)})
    links={
      'internal':[{'url':x['url'],'type':'internal','nofollow':False} for x in agent.get('internal_links',[])],
      'external':[{'url':x['url'],'type':'external','nofollow':bool(x.get('nofollow',False))} for x in agent.get('external_links',[])]
    }
    return {
      'schema_version':'phase3b-seo-bundle-v0.1',
      'identity':{'part_number':pn,'manufacturer':product['identity'].get('manufacturer'),'product_category':product['identity'].get('product_category'),'content_mode':content_mode},
      'content':{'body_markdown':body_markdown},
      'page':{'product_title':agent['product_title'],'slug':product_slug(pn, product['identity'].get('product_category')),'canonical_url':None},
      'snippet':{'seo_title':agent['seo_title'],'meta_description':agent['meta_description']},
      'seo':{'focus_keyword':pn},
      'images':images,'links':links,
      'technical_safety':{'facts_path':product['source'].get('facts_path'),'fact_status':product['source']['fact_status']},
      'source':{'datasheet_status':product['source']['datasheet_status'],'datasheet_path':product['source'].get('datasheet_path')},
      'generation':{'generator_version':generator_version,'attempt':attempt}
    }
