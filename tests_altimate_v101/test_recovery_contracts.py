from __future__ import annotations
import json
from copy import deepcopy
from pathlib import Path

from pypdf import PdfWriter

from metadata_manager import load_or_create, save, save_phase2, save_admin_override
from phase2.metadata_state import is_phase2_eligible
from phase2.pipeline import Phase2Pipeline
from recover_datasheet_authority import propose, run


def _record(root, pn='TEST100'):
    (root/'metadata').mkdir(exist_ok=True)
    path, rec = load_or_create(root, pn)
    rec['part_number'] = pn
    save(path, rec)
    return path, rec


def _pdf(root, pn):
    out=root/'datasheets'/f'{pn}.pdf'
    out.parent.mkdir(exist_ok=True)
    writer=PdfWriter();writer.add_blank_page(width=400,height=400)
    with out.open('wb') as file:writer.write(file)
    return out


def _metadata(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_manual_pdf_is_immutable_against_late_phase2(tmp_path):
    path, base = _record(tmp_path)
    _pdf(tmp_path,'TEST100')
    original=deepcopy(base)
    admin=deepcopy(base)
    admin['datasheet'].update(status='completed', file='datasheets/TEST100.pdf',searched_part_number='TEST100',verified_exact_match=True)
    admin['admin_audit']['history'].append({'action':'MANUAL_DATASHEET_ATTACHED','part_number':'TEST100','file':'datasheets/TEST100.pdf'})
    save_admin_override(path,admin)
    obsolete=deepcopy(original);obsolete['datasheet'].update(status='web_error',file=None)
    save_phase2(path, obsolete)
    live=_metadata(path)
    assert live['datasheet']['status']=='completed'
    assert live['datasheet']['file']=='datasheets/TEST100.pdf'
    ok, reason=is_phase2_eligible(deepcopy(live),tmp_path)
    assert not ok and reason=='VALID_COMPLETED_PDF'


def test_sales_only_not_overwritten(tmp_path):
    path, data=_record(tmp_path)
    obsolete=deepcopy(data)
    data['datasheet'].update(status='sales_only_no_datasheet',file=None,sales_only_authorized=True)
    data['admin_audit']['history'].append({'action':'ADMIN_SALES_ONLY_AFTER_WEB_ERROR','part_number':'TEST100'})
    save_admin_override(path,data)
    obsolete['datasheet']['status']='web_error'
    save_phase2(path,obsolete)
    assert _metadata(path)['datasheet']['status']=='sales_only_no_datasheet'
    ok,_=is_phase2_eligible(_metadata(path),tmp_path)
    assert not ok


def test_pipeline_skip_protected_does_not_call_network(tmp_path):
    path, data=_record(tmp_path)
    _pdf(tmp_path,'TEST100')
    data['datasheet'].update(status='completed',searched_part_number='TEST100',file='datasheets/TEST100.pdf')
    save_admin_override(path,data)
    from phase2.metadata_state import MetadataStore
    pipeline=Phase2Pipeline(project_root=tmp_path,metadata_dir=tmp_path/'metadata',
                            datasheet_dir=tmp_path/'datasheets',proxy_file=tmp_path/'proxies.txt',
                            api_key='NO_NETWORK',metadata_store=MetadataStore(tmp_path,save_callback=save_phase2))
    def network_must_not_run(): raise AssertionError('Network must not run for a protected PDF')
    pipeline._ensure_network=network_must_not_run
    assert pipeline.process_batch([path])==0
    assert _metadata(path)['datasheet']['status']=='completed'


def test_recovery_pdf_is_non_destructive_and_idempotent(tmp_path):
    path, data=_record(tmp_path)
    _pdf(tmp_path,'TEST100')
    data['datasheet'].update(status='web_error',file=None)
    data['admin_audit']['history'].append({'action':'MANUAL_DATASHEET_ATTACHED','part_number':'TEST100','file':'datasheets/TEST100.pdf'})
    data['admin_audit']['status']='READY_FOR_REAUDIT'
    data['phase3']['status']='completed'
    save_admin_override(path,data)
    before=path.read_bytes()
    rows=run(tmp_path)
    assert next(r for r in rows if r['part_number']=='TEST100')['action']=='RESTORE_MANUAL_PDF'
    assert path.read_bytes()==before
    rows=run(tmp_path,apply=True)
    live=_metadata(path)
    assert live['datasheet']['status']=='completed'
    assert live['phase3']['status']=='completed'
    assert live['admin_audit']['status']=='READY_FOR_REAUDIT'
    assert any((tmp_path/'audit_history').rglob('TEST100.json'))
    assert not any(r['action']=='RESTORE_MANUAL_PDF' for r in run(tmp_path))


def test_recovery_sales_only_does_not_approve(tmp_path):
    path, data=_record(tmp_path)
    data['datasheet'].update(status='web_error',file=None)
    data['admin_audit']['history'].append({'action':'ADMIN_SALES_ONLY_AFTER_WEB_ERROR','part_number':'TEST100','at':'2026-10-14T13:00:00Z'})
    data['admin_audit']['status']='READY_FOR_REAUDIT'
    save_admin_override(path,data)
    run(tmp_path,apply=True)
    live=_metadata(path)
    assert live['datasheet']['status']=='sales_only_no_datasheet'
    assert live['datasheet']['sales_only_authorized'] is True
    assert live['admin_audit']['status']=='READY_FOR_REAUDIT'
    assert live['datasheet']['file'] is None


def test_recovery_does_not_guess_or_restore_missing_pdf(tmp_path):
    path, data=_record(tmp_path)
    data['datasheet']['status']='web_error'
    data['admin_audit']['history'].append({'action':'MANUAL_DATASHEET_ATTACHED','part_number':'TEST100','file':'datasheets/TEST100.pdf'})
    save_admin_override(path,data)
    kind,reason,new=propose(tmp_path,path,_metadata(path))
    assert kind=='MANUAL_REVIEW' and new is None
    assert 'MISSING' in reason


def test_recovery_approved_status_unchanged(tmp_path):
    path, data=_record(tmp_path)
    _pdf(tmp_path,'TEST100')
    data['datasheet']['status']='web_error'
    data['admin_audit']['history'].append({'action':'MANUAL_DATASHEET_ATTACHED','part_number':'TEST100','file':'datasheets/TEST100.pdf'})
    data['admin_audit']['status']='APPROVED'
    save_admin_override(path,data)
    run(tmp_path,apply=True)
    assert _metadata(path)['admin_audit']['status']=='APPROVED'


def test_old_worker_cannot_overwrite_manual_history_even_if_current_web_error(tmp_path):
    path,data=_record(tmp_path)
    _pdf(tmp_path,'TEST100')
    data['datasheet']['status']='web_error'
    data['admin_audit']['history'].append({'action':'MANUAL_DATASHEET_ATTACHED','part_number':'TEST100','file':'datasheets/TEST100.pdf'})
    save_admin_override(path,data)
    obsolete=deepcopy(data);obsolete['datasheet']['status']='failed'
    save_phase2(path,obsolete)
    assert _metadata(path)['datasheet']['status']=='web_error'  # don't make it worse; explicit recovery required


def test_stale_phase2_cannot_undo_part_number_change(tmp_path):
    path,data=_record(tmp_path)
    _pdf(tmp_path,'TEST100')
    data['datasheet'].update(status='completed',file='datasheets/TEST100.pdf',searched_part_number='TEST100')
    save_admin_override(path,data)
    changed=deepcopy(data); changed['part_number']='TEST101'
    changed['datasheet']['searched_part_number']='TEST101'
    changed['datasheet']['status']='web_error';changed['datasheet']['file']=None
    save_phase2(path,changed)
    assert _metadata(path)['part_number']=='TEST100'
