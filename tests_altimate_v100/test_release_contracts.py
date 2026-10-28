from __future__ import annotations
import json
import shutil
from pathlib import Path
from copy import deepcopy

from metadata_manager import load_or_create, save, save_phase2, save_phase3
from admin_audit import diagnose_audit, accept_rejected_image
from orchestrator.api_coordinator import SharedCooldown


def test_metadata_late_p1_preserves_p2_p3_and_audit(tmp_path):
    path, initial = load_or_create(tmp_path, 'part_s1')
    initial['part_number'] = 'ABC1234'
    save(path, initial)
    baseline = deepcopy(initial)
    p2 = deepcopy(baseline)
    p2['datasheet']['status'] = 'completed'
    p2['datasheet']['updated_at'] = '2026-10-14T18:30:00Z'
    save_phase2(path, p2)
    p3 = deepcopy(baseline)
    p3['phase3']['status'] = 'completed'
    p3['phase3']['tone_status'] = 'PASS'
    save_phase3(path, p3)
    stale_p1 = deepcopy(baseline)
    stale_p1['image_optimization']['status'] = 'completed'
    save(path, stale_p1)
    persisted = json.loads(path.read_text(encoding='utf-8'))
    assert persisted['datasheet']['status'] == 'completed'
    assert persisted['phase3']['tone_status'] == 'PASS'
    assert persisted['image_optimization']['status'] == 'completed'


def test_audit_rejected_reason_is_actionable(tmp_path):
    data={'part_number':'ABC1234','identity_validation':{'status':'rejected','issues':['lead_structure_mismatch']},'datasheet':{'status':'web_error'}}
    diag = diagnose_audit(tmp_path, data, None)
    codes = [d['code'] for d in diag]
    assert 'IMAGE_IDENTITY_REJECTED' in codes
    assert 'DATASHEET_WEB_ERROR' in codes
    assert all(d['action'] for d in diag)


def test_api_cooldown_has_no_arbitrary_default_delay():
    x=SharedCooldown()
    x.before_request()
    assert x._until == 0


def test_accept_existing_canvas_without_any_model_calls(tmp_path):
    root=Path(__file__).resolve().parents[1]
    pn='SSP5N90A'
    for d in ('metadata','output','assets'):
        (tmp_path/d).mkdir()
    shutil.copy2(root/'metadata'/f'{pn}.json', tmp_path/'metadata'/f'{pn}.json')
    shutil.copy2(root/'output'/f'{pn}_canvas.png', tmp_path/'output'/f'{pn}_canvas.png')
    shutil.copy2(root/'assets/store_logo.png', tmp_path/'assets/store_logo.png')
    result=accept_rejected_image(tmp_path,tmp_path/'metadata'/f'{pn}.json')
    assert Path(result['final_path']).exists()
    persisted=json.loads((tmp_path/'metadata'/f'{pn}.json').read_text(encoding='utf-8'))
    assert persisted['image_optimization']['status'] == 'completed'
    assert persisted['identity_validation']['history'][-1]['action'] == 'ADMIN_ACCEPTED_AFTER_REJECTION'
    assert persisted['admin_audit']['history'][-1]['action'] == 'ADMIN_ACCEPTED_REJECTED_IMAGE'
