import json
from pathlib import Path
from PIL import Image

from admin_audit import approve_item, disapprove_item, list_audit_items, post_phase2_admin_hook, prepare_pn_input_metadata
from metadata_manager import load_or_create, save, rename_metadata_to_partnumber


def _dirs(root: Path):
    for name in ('metadata','input','PN_input','output','Final','datasheets','phase3_outputs','products','work/content','work/fact_extraction','ready_for_upload','runtime_state','audit_history'):
        (root/name).mkdir(parents=True,exist_ok=True)


def _img(path: Path, fmt=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    Image.new('RGB',(80,80),'white').save(path,fmt or path.suffix.lstrip('.').upper())


def _p3_state(pn: str, body=None):
    return {
        'schema_version':'phase3-altimate-product-v1',
        'identity':{'part_number':pn,'manufacturer':None,'product_type_label':'آی سی','product_category':'IC','verified_package_installation':'DIP-8'},
        'source':{'datasheet_status':'NO_FULL_DATASHEET','fact_status':'NOT_RUN'},
        'seo':{'focus_keyword':pn},
        'page':{'product_title':f'آی سی {pn}','slug':pn.lower(),'canonical_url':None},
        'snippet':{},
        'content':{'body_markdown':body or f'محتوای فروش {pn}','html_path':f'{pn}.html','publishing_source':'html','direction':'rtl'},
        'images':[], 'links':{}, 'internal_link_policy':{},
        'woocommerce':{'attributes':{'part_number':pn,'package_installation':'DIP-8'}},
        'generation':{},'tone_editor':{},
        'validation':{'final_seo_score':80,'publishable':True,'final_semantic_audit':{'status':'PASS'}},
        'evaluation_scorecard':{'tone':{'status':'PASS','naturalness_score':90}},
        'publishing':{'target':'woocommerce','status':'NOT_SENT','wordpress_product_id':None,'publish_mode':'DRAFT','description_format':'html','description_path':f'{pn}.html','direction':'rtl'},
    }


def _make_finalized(root: Path, ref='IMG_1', pn='OLD123', ds_status='not_found_confirmed'):
    _dirs(root)
    original=root/'input'/f'{ref}.JPG'; _img(original,'JPEG')
    final=root/'Final'/f'{pn}.webp'; _img(final,'WEBP')
    meta,data=load_or_create(root,ref)
    data['part_number']=pn; data['product_title']=f'آی سی {pn}'
    data['original_image']['file']=f'input/{ref}.JPG'
    for key in ('precheck','regeneration','logo'):
        data[key]['status']='completed'
    data['identity_validation'].update({'status':'completed','pass':True})
    data['ocr'].update({'status':'completed','primary_code':pn})
    data['image_optimization'].update({'status':'completed','file':f'Final/{pn}.webp','format':'WEBP','width':1254,'height':1254,'size_kb':80,'quality':90,'completed_at':'x'})
    data['datasheet'].update({'status':ds_status,'searched_part_number':pn})
    data['package'].update({'value':'DIP-8','source':'datasheet_pdf','status':'resolved','resolved_by':'phase3','exact_part_number_match':True})
    data['phase3'].update({'status':'completed','facts_status':'NOT_RUN','content_status':'completed','json_file':f'phase3_outputs/{pn}.json','content_file':f'phase3_outputs/{pn}.html'})
    save(meta,data); meta=rename_metadata_to_partnumber(root,meta,data)
    state=_p3_state(pn)
    (root/'phase3_outputs'/f'{pn}.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    (root/'phase3_outputs'/f'{pn}.html').write_text(f'<p>{pn} {pn}</p>',encoding='utf-8')
    (root/'products'/f'{pn}.json').write_text(json.dumps({'product_id':pn},ensure_ascii=False),encoding='utf-8')
    return meta


def test_pn_input_sets_trusted_pn_and_skips_ocr(tmp_path):
    _dirs(tmp_path)
    image=tmp_path/'PN_input'/'TC123ABC.jpg'; _img(image,'JPEG')
    meta,_=prepare_pn_input_metadata(tmp_path,image)
    saved=json.loads(meta.read_text(encoding='utf-8'))
    assert saved['part_number']=='TC123ABC'
    assert saved['product_title']=='آی سی TC123ABC'
    assert saved['ocr']['status']=='manual_override'
    assert saved['ocr']['manual_authority']=='PN_INPUT_FILENAME'
    assert saved['original_image']['file']=='PN_input/TC123ABC.jpg'


def test_audit_list_marks_complete_and_incomplete(tmp_path):
    _make_finalized(tmp_path)
    items=list_audit_items(tmp_path)
    assert items[0]['classification']=='FINALIZED'
    failed,data=load_or_create(tmp_path,'IMG_BAD')
    data['ocr']['status']='failed'; data['ocr']['last_error']='max_output_tokens'; save(failed,data)
    items=list_audit_items(tmp_path)
    assert items[0]['classification']=='AUDIT_NEEDED'
    assert any(x['classification']=='FINALIZED' for x in items)


def test_approve_builds_v3_canonical_bundle(tmp_path):
    meta=_make_finalized(tmp_path,pn='APP123')
    result=approve_item(tmp_path,meta)
    bundle=Path(result['ready_bundle'])
    assert (bundle/'product.json').exists()
    assert (bundle/'product.html').exists()
    assert (bundle/'APP123.webp').exists()
    product=json.loads((bundle/'product.json').read_text(encoding='utf-8'))
    assert product['product_title']=='آی سی APP123'
    assert product['package']=='DIP-8'
    assert product['wordpress']['category']=={'parent':'قطعات الکترونیکی','child':'آی سی'}
    saved=json.loads(meta.read_text(encoding='utf-8'))
    assert saved['admin_audit']['status']=='APPROVED'
    assert saved['publishing']['bundle_status']=='READY'


def test_wrong_pn_renames_metadata_final_and_invalidates_p2(tmp_path):
    meta=_make_finalized(tmp_path,pn='WRONG1')
    result=disapprove_item(tmp_path,meta,['wrong_part_number'],corrected_pn='RIGHT1')
    new_meta=Path(result['metadata_path'])
    saved=json.loads(new_meta.read_text(encoding='utf-8'))
    assert new_meta.name=='RIGHT1.json'
    assert saved['part_number']=='RIGHT1'
    assert saved['product_title']=='آی سی RIGHT1'
    assert saved['datasheet']['status']=='pending'
    assert saved['package']['value'] is None
    assert saved['admin_audit']['force_phase2'] is True


def test_wrong_datasheet_resets_phase2_same_pn(tmp_path):
    meta=_make_finalized(tmp_path,pn='DS123')
    result=disapprove_item(tmp_path,meta,['wrong_data_sheet'])
    saved=json.loads(Path(result['metadata_path']).read_text(encoding='utf-8'))
    assert saved['part_number']=='DS123'
    assert saved['datasheet']['status']=='pending'
    assert saved['package']['value'] is None
    assert saved['admin_audit']['force_phase2'] is True
    assert saved['admin_audit']['force_fact_extraction'] is True


def test_no_datasheet_to_no_datasheet_programmatic_pn_repair_has_exact_title(tmp_path):
    meta=_make_finalized(tmp_path,pn='OLDPN')
    result=disapprove_item(tmp_path,meta,['wrong_part_number'],corrected_pn='NEWPN')
    new_meta=Path(result['metadata_path'])
    data=json.loads(new_meta.read_text(encoding='utf-8'))
    data['datasheet']['status']='not_found_confirmed'; save(new_meta,data)
    hook=post_phase2_admin_hook(tmp_path,new_meta)
    assert hook['handled_locally'] is True
    state=json.loads((tmp_path/'phase3_outputs'/'NEWPN.json').read_text(encoding='utf-8'))
    assert state['page']['product_title']=='آی سی NEWPN'


def test_wrong_pn_contract_ignores_wrong_ds_and_seo_flags(tmp_path):
    meta=_make_finalized(tmp_path,pn='A1')
    result=disapprove_item(tmp_path,meta,['wrong_part_number','wrong_data_sheet','seo_content_regeneration_needed'],corrected_pn='A2')
    saved=json.loads(Path(result['metadata_path']).read_text(encoding='utf-8'))
    assert saved['admin_audit']['selected_issues']==['wrong_part_number']
    assert saved['admin_audit']['force_phase2'] is True
    assert saved['admin_audit']['force_seo'] is True
