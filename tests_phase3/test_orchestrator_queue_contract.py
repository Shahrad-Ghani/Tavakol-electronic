from pathlib import Path

from orchestrator.engine import IntegratedOrchestrator
from orchestrator.events import EventLogger
from metadata_manager import load_or_create, save


def test_part_number_callback_queues_phase2_immediately_and_only_once(tmp_path):
    logger=EventLogger(tmp_path)
    orch=IntegratedOrchestrator(tmp_path,logger)
    meta,data=load_or_create(tmp_path,'TC427CPA','ic')
    data['part_number']='TC427CPA'
    save(meta,data)
    cb=orch._pn_ready_callback('image_001')
    cb(meta,data,'image_001')
    assert orch._p2q.qsize()==1
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
