import json
from copy import deepcopy

from metadata_manager import load_or_create, save, save_phase2
from core.package_resolution import apply_package_candidate


def _seed(tmp_path):
    (tmp_path/'metadata').mkdir(parents=True, exist_ok=True)
    path, data=load_or_create(tmp_path,'source_1','IC')
    data['part_number']='TC427CPA'; data['product_title']='آی سی TC427CPA'
    data['ocr'].update({'status':'completed','primary_code':'TC427CPA'})
    save(path,data)
    return path, json.loads(path.read_text(encoding='utf-8'))


def test_late_phase1_save_cannot_erase_phase2_checkpoint(tmp_path):
    path, base=_seed(tmp_path)
    stale_p1=deepcopy(base); stale_p2=deepcopy(base)
    stale_p2['datasheet'].update({
        'status':'identity_found_unresolved','searched_part_number':'TC427CPA','matched_part_number':'TC427CPA',
        'verified_exact_match':True,'manufacturer':'Microchip','manufacturer_country':'United States',
        'mouser_part_number':'TC427CPA','updated_at':'2026-09-03T15:00:00Z',
    })
    stale_p2['manufacturer']='Microchip'; stale_p2['country']='United States'
    apply_package_candidate(stale_p2,value='PDIP-8',source='mouser',resolved_by='phase2',exact_part_number_match=True,attribute_name='Package / Case')
    save_phase2(path,stale_p2)

    stale_p1['logo'].update({'status':'completed','file':'assets/store_logo.png','completed_at':'2026-09-03T15:00:01Z'})
    save(path,stale_p1)

    final=json.loads(path.read_text(encoding='utf-8'))
    assert final['logo']['status']=='completed'
    assert final['package']['value']=='PDIP-8'
    assert final['datasheet']['verified_exact_match'] is True
    assert final['manufacturer']=='Microchip'


def test_late_phase2_save_cannot_erase_phase1_checkpoint(tmp_path):
    path, base=_seed(tmp_path)
    stale_p1=deepcopy(base); stale_p2=deepcopy(base)
    stale_p1['image_optimization'].update({'status':'completed','file':'Final/TC427CPA.webp','format':'WEBP','width':1254,'height':1254,'size_kb':72.0,'quality':80,'completed_at':'2026-09-03T15:00:01Z'})
    save(path,stale_p1)
    stale_p2['datasheet'].update({'status':'not_found_confirmed','searched_part_number':'TC427CPA','updated_at':'2026-09-03T15:00:02Z'})
    save_phase2(path,stale_p2)
    final=json.loads(path.read_text(encoding='utf-8'))
    assert final['image_optimization']['status']=='completed'
    assert final['image_optimization']['file']=='Final/TC427CPA.webp'
    assert final['datasheet']['status']=='not_found_confirmed'
