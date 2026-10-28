from orchestrator.adapter import reconcile_package
from orchestrator.runtime_guard import classify_exception


def test_package_reconciliation_confirms_equal_phase2_and_phase3():
    meta={'package':{'value':'SOIC-8','status':'resolved','source':'mouser','resolved_by':'phase2'}}
    p3={'woocommerce':{'attributes':{'package_installation':'SOIC-8'}}}
    out=reconcile_package(meta,p3)
    assert out['value']=='SOIC-8'
    assert out['status']=='CONFIRMED_MOUSER_AND_DATASHEET'
    assert out['phase2_mouser']=='SOIC-8'


def test_package_conflict_is_visible_and_phase2_remains_canonical():
    meta={'package':{'value':'PDIP-8','status':'resolved','source':'mouser','resolved_by':'phase2'}}
    p3={'woocommerce':{'attributes':{'package_installation':'SOIC-8'}}}
    out=reconcile_package(meta,p3)
    assert out['value']=='PDIP-8'
    assert out['status']=='CONFLICT_REVIEW'
    assert out['phase2_mouser']=='PDIP-8'
    assert out['phase3_datasheet']=='SOIC-8'


def test_runtime_error_classifier_distinguishes_network_from_fatal_account_errors():
    assert classify_exception(RuntimeError('401 invalid api key')).fatal is True
    assert classify_exception(RuntimeError('insufficient_quota billing credit exhausted')).fatal is True
    assert classify_exception(RuntimeError('Mouser API returned Errors: Daily Search API call limit exceeded')).kind == 'API_CREDIT_EXHAUSTED'
    assert classify_exception(RuntimeError('MOUSER_API_KEY is missing')).kind == 'API_AUTH_INVALID'
    net=classify_exception(TimeoutError('connection timed out'))
    assert net.retryable is True and net.fatal is False
