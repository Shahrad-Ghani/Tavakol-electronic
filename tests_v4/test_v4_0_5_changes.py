"""Offline regressions grounded in the October 2026 WooCommerce HTML captures."""
import copy
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from core import category_registry
from core.category_management import CategoryAlreadyExists, add_category, remove_category
from phase3_fact_extraction.mosfet_specs import extract_mosfet_specs
from phase4.publisher import ProductBundle, _attribute_pairs
from phase4.publisher_state import PublisherStateStore, REQUIRED_STEPS


def test_real_category_dom_id_suffix_and_scope():
    # Captured actual Add Product DOM: the popular list and all-categories list
    # contain different IDs. Using #in-product_cat-110 alone is incorrect.
    html = '''<div id="product_catdiv"><ul id="product_catchecklist">
    <li><label class="selectit"><input id="in-product_cat-110-2" name="tax_input[product_cat][]" type="checkbox" value="110"> قطعات الکترونیکی</label></li>
    <li><label class="selectit"><input id="in-product_cat-115-2" name="tax_input[product_cat][]" type="checkbox" value="115"> ماسفت</label></li>
    </ul><ul id="product_catchecklist-pop"><li><input id="in-popular-product_cat-110" type="checkbox" value="110"></li></ul></div>'''
    parsed = BeautifulSoup(html,'html.parser')
    for term in (110,115):
        matches = parsed.select(f'#product_catchecklist input[name="tax_input[product_cat][]"][value="{term}"]')
        assert len(matches) == 1
        assert matches[0]['id'].endswith('-2')
    assert not parsed.select('#product_catchecklist input[id^="in-popular"]')


def test_snippet_dom_exact_control_ids_and_default_title():
    html = '''<div class="components-modal__children-container"><input id="rank-math-editor-title" value="%title% %sep% %sitename%"/>
    <input id="rank-math-editor-permalink" value=""/><textarea id="rank-math-editor-description"></textarea></div>'''
    parsed = BeautifulSoup(html,'html.parser')
    assert parsed.select_one('#rank-math-editor-title')['value'] == '%title% %sep% %sitename%'
    assert parsed.select_one('#rank-math-editor-permalink') is not None
    assert parsed.select_one('#rank-math-editor-description') is not None


def test_publisher_step_names_match_version_405():
    assert 'snippet' in REQUIRED_STEPS
    assert 'sku' in REQUIRED_STEPS
    assert 'permalink' not in REQUIRED_STEPS


def test_legacy_state_snippet_migrates(tmp_path):
    folder = tmp_path/'runtime_state'/'publisher'
    folder.mkdir(parents=True)
    (folder/'PN123.json').write_text(json.dumps({'steps':{'permalink':{'status':'success'}},'status':'RUNNING'}))
    data = PublisherStateStore(tmp_path).load('PN123')
    assert data['steps']['snippet']['status'] == 'success'
    assert 'sku' in data['steps']


def _bundle(**changes):
    args = dict(pn='IRF123',title='ماسفت IRF123',package=None,html_path=Path('product.html'),
                html='<p>some text</p>', short_description_html='description', image_path=Path('image.png'),
                datasheet_path=None,datasheet_status='not_found_confirmed',product_json_path=Path('product.json'),
                category_key='mosfet', category_parent='قطعات الکترونیکی', category_child='ماسفت',
                category_parent_term_id=110, category_term_id=115, slug='irf123-mosfet',
                seo_title='خرید ماسفت IRF123',meta_description='meta')
    args.update(changes)
    return ProductBundle(**args)


def test_mosfet_attribute_rows_with_missing():
    specs={'channel_type':{'value':'N-Channel'},'vds':{'value':'60 V'},'id_continuous':{'value':None}}
    pairs,missing = _attribute_pairs(_bundle(mosfet_specs=specs,package='TO-92'))
    assert pairs == [('Part Number','IRF123'),('پکیج','TO-92'),('Channel Type','N-Channel'),('مشخصات فنی','VDS: 60 V')]
    assert missing==['id_continuous']


def test_strict_continuous_current_vs_pulsed_and_on_state():
    facts = {'seo_ready_facts':[
        {'id':'1','parameter':'Device type','claim':'N-channel enhancement MOSFET'},
        {'id':'2','parameter':'Drain-source breakdown voltage','value_text':'60 min','unit':'V','claim':'VDS 60 V minimum'},
        {'id':'3','parameter':'On-State Drain Current','value_text':'3','unit':'A','claim':'3 A on state'},
        {'id':'4','parameter':'Pulsed Drain Current','value_text':'9','unit':'A','claim':'pulsed 9 A'},
    ]}
    out=extract_mosfet_specs(facts)
    assert out['channel_type']['value']=='N-Channel'
    assert out['vds']['value']=='60 V'
    assert out['id_continuous']['value'] is None
    assert 'id_continuous' in out['missing']
    facts['seo_ready_facts'].append({'id':'5','parameter':'Continuous Drain Current',
                                      'value_text':'200','unit':'mA','claim':'Continuous drain current 200 mA'})
    assert extract_mosfet_specs(facts)['id_continuous']['value']=='200 mA'


def test_software_only_dynamic_category_edit(tmp_path,monkeypatch):
    registry = {'schema_version':'1.0','categories':{'ic':copy.deepcopy(category_registry.category_context('ic'))}}
    del registry['categories']['ic']['key']
    file=tmp_path/'categories.json'
    file.write_text(json.dumps(registry,ensure_ascii=False),encoding='utf8')
    monkeypatch.setattr(category_registry,'REGISTRY_PATH',file)
    category_registry.load_registry.cache_clear()
    try:
        key=add_category(display_name='JFET',parent='قطعات الکترونیکی',wordpress_child='JFET',
                         title_prefix='ترانزیستور JFET',density_phrase='این JFET',
                         category_url='https://tavakolelectronic.com/product-category/jfet/',registry_path=file)
        assert category_registry.product_title('ABC','JFET')=='ترانزیستور JFET ABC'
        assert category_registry.category_context(key)['wordpress']['term_id']==0
        with pytest.raises(CategoryAlreadyExists,match='Category already exists'):
            add_category(display_name='jfet',parent='قطعات الکترونیکی',wordpress_child='JFET',
                         title_prefix='JFET',category_url='https://tavakolelectronic.com/jfet/',registry_path=file)
        remove_category(key,registry_path=file)
        assert key not in category_registry.category_keys()
        # Still resolves historical approved metadata.
        assert category_registry.category_context(key)['display_name']=='JFET'
    finally:
        category_registry.load_registry.cache_clear()


def test_dynamic_category_unknown_term_id_can_be_bundled_for_exact_site_lookup(tmp_path, monkeypatch):
    from core.category_integrity import assert_bundle_category_consistency
    registry = {'schema_version':'1.0', 'categories': {'ic': copy.deepcopy(category_registry.category_context('ic'))}}
    del registry['categories']['ic']['key']
    file=tmp_path/'registry.json'
    file.write_text(json.dumps(registry,ensure_ascii=False))
    monkeypatch.setattr(category_registry,'REGISTRY_PATH',file)
    category_registry.load_registry.cache_clear()
    try:
        k=add_category(display_name='Custom JFET', parent='قطعات الکترونیکی',wordpress_child='JFET',
                       title_prefix='JFET',category_url='https://tavakolelectronic.com/product-category/قطعات-الکترونیکی/jfet/',registry_path=file)
        product={'part_number':'ABC100','product_type':k,'category':category_registry.category_context(k),
                 'product_title':'JFET ABC100','seo':{'permalink':'abc100-custom-jfet'},
                 'wordpress':{'category_key':k,'category':{'parent':'قطعات الکترونیکی','child':'JFET'},
                              'category_parent_term_id':110,'category_term_id':0}}
        assert assert_bundle_category_consistency(product).key==k
    finally:
        category_registry.load_registry.cache_clear()
