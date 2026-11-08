from pathlib import Path
import json

from orchestrator.engine import IntegratedOrchestrator
from orchestrator.events import EventLogger
from metadata_manager import load_or_create, save
from core.metadata_v3 import get_category_key


def test_part_number_callback_queues_phase2_immediately_and_only_once(tmp_path):
    logger=EventLogger(tmp_path)
    orch=IntegratedOrchestrator(tmp_path,logger,category_key='mosfet')
    meta,data=load_or_create(tmp_path,'TC427CPA','igbt_transistor')
    data['part_number']='TC427CPA'
    save(meta,data)
    cb=orch._pn_ready_callback('image_001')
    cb(meta,data,'image_001')
    assert orch._p2q.qsize()==1
    # A different category selected for this run must not reclassify existing metadata.
    persisted=json.loads(meta.read_text(encoding='utf-8'))
    assert get_category_key(persisted)=='igbt_transistor'
    state=orch.state.load('image_001')
    assert state['phase1']=='PN_READY'
    assert state['phase2']=='QUEUED'
    # A duplicate callback from a resume/checkpoint cannot duplicate work.
    cb(meta,data,'image_001')
    assert orch._p2q.qsize()==1


def test_phase2_terminal_event_queues_phase3_immediately_and_only_once(tmp_path):
    logger=EventLogger(tmp_path)
    orch=IntegratedOrchestrator(tmp_path,logger)
    meta=tmp_path/'metadata'/'TC427CPA.json'
    meta.parent.mkdir(parents=True,exist_ok=True)
    orch._enqueue_p3('image_001',meta,'TC427CPA')
    assert orch._p3q.qsize()==1
    assert orch.state.load('image_001')['phase3']=='QUEUED'
    orch._enqueue_p3('image_001',meta,'TC427CPA')
    assert orch._p3q.qsize()==1



def test_resume_scan_never_reassigns_existing_metadata_category(tmp_path):
    logger=EventLogger(tmp_path)
    meta,data=load_or_create(tmp_path,'IGBT_RESUME_01','igbt_transistor')
    data['part_number']='IGBT_RESUME_01'
    data['datasheet']['status']='web_error'
    save(meta,data)

    orch=IntegratedOrchestrator(tmp_path,logger,category_key='mosfet')
    orch._resume_scan()

    persisted=json.loads(meta.read_text(encoding='utf-8'))
    assert get_category_key(persisted)=='igbt_transistor'


def test_phase1_receives_selected_category_for_new_metadata(monkeypatch,tmp_path):
    import pipeline as phase1

    seen={}
    source=tmp_path/'input'/'new_product_image.png'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'not-read-because-checkpoint-is-mocked')
    meta=tmp_path/'metadata'/'new_product_image.json'
    data={'part_number':'NEWPN123','image_optimization':{'status':'completed','file':'Final/NEWPN123.webp'}}

    def fake_load_or_create(root,ref,category='IC'):
        seen['category']=category
        return meta,data

    monkeypatch.setattr(phase1,'load_or_create',fake_load_or_create)
    monkeypatch.setattr(phase1,'rename_metadata_to_partnumber',lambda root,path,record:path)
    monkeypatch.setattr(phase1,'image_finalized',lambda record:True)
    monkeypatch.setattr(phase1,'log',lambda *args,**kwargs:None)

    phase1.process_one(
        None,source,tmp_path/'phase1.log',
        category_key='igbt_transistor',
    )

    assert seen['category']=='igbt_transistor'
