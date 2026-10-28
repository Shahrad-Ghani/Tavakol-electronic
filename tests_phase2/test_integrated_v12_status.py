import json
from PIL import Image
from metadata_manager import load_or_create, save


def test_v3_save_has_one_detailed_image_status_source(tmp_path):
    (tmp_path / 'metadata').mkdir()
    path, data = load_or_create(tmp_path, 'IMG_1', 'IC')
    data['image_optimization'].update({
        'status':'completed','format':'WEBP','width':1254,'height':1254,
        'size_kb':80.0,'quality':90,'file':'Final/TEST.webp','completed_at':'2026-09-06T00:00:00Z',
    })
    save(path,data)
    persisted=json.loads(path.read_text(encoding='utf-8'))
    assert 'status' not in persisted
    assert persisted['image_optimization']['status']=='completed'


def test_v3_repairs_legacy_absolute_final_path_without_openai(tmp_path, monkeypatch):
    import sys, types
    openai_mod = sys.modules.get('openai')
    if openai_mod is None or not hasattr(openai_mod, 'OpenAI'):
        fake_openai=types.ModuleType('openai')
        class _DummyOpenAI: pass
        fake_openai.OpenAI=_DummyOpenAI
        sys.modules['openai']=fake_openai
    import orchestrator.engine as engine_mod
    from orchestrator.engine import IntegratedOrchestrator
    for name in ('metadata','output','Final','assets','logs','runtime_state','input'):
        (tmp_path/name).mkdir(parents=True,exist_ok=True)
    final=tmp_path/'Final'/'LEGACY123.webp'
    Image.new('RGB',(1254,1254),'white').save(final,'WEBP')
    meta_path,data=load_or_create(tmp_path,'IMG_LEGACY','IC')
    data['part_number']='LEGACY123'; data['product_title']='آی سی LEGACY123'
    data['image_optimization'].update({'status':'completed','format':'WEBP','width':1254,'height':1254,'size_kb':80.0,'quality':90,'file':r'C:\\OLD_REPO\\Final\\LEGACY123.webp','completed_at':'2026-09-03T20:00:00Z'})
    save(meta_path,data)
    called=[]
    monkeypatch.setattr(engine_mod,'process_one',lambda *a,**k: called.append(True))
    engine=IntegratedOrchestrator(tmp_path)
    engine._run_phase1_image(tmp_path/'input'/'IMG_LEGACY.JPG')
    assert called==[]
    canonical=json.loads(meta_path.read_text(encoding='utf-8'))
    assert canonical['image_optimization']['status']=='completed'
    assert canonical['image_optimization']['file']=='Final/LEGACY123.webp'
