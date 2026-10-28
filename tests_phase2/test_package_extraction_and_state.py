from pathlib import Path

from phase2.metadata_state import apply_result, default_datasheet_state
from phase2.resolver_v43 import Result, extract_mouser_package


def test_extracts_physical_package_case_from_product_attributes():
    item = {
        'Packaging': 'Reel',
        'ProductAttributes': [
            {'AttributeName': 'Package / Case', 'AttributeValue': 'SOIC-8'},
            {'AttributeName': 'Mounting Style', 'AttributeValue': 'SMD/SMT'},
        ],
    }
    value, attr = extract_mouser_package(item)
    assert value == 'SOIC-8'
    assert attr == 'Package / Case'


def test_never_treats_sales_packaging_as_ic_package():
    value, attr = extract_mouser_package({'Packaging': 'Cut Tape', 'ProductAttributes': []})
    assert value == ''
    assert attr == ''


def test_package_is_persisted_only_for_exact_mouser_identity(tmp_path):
    data = {'part_number':'TC427CPA','datasheet':default_datasheet_state(),'package':{'value':None,'source':None,'attribute_name':None,'status':'unresolved','resolved_by':None,'exact_part_number_match':False,'sources_tried':[],'updated_at':None}}
    result = Result(
        part_number='TC427CPA', status='IDENTITY_FOUND_DATASHEET_UNRESOLVED',
        matched_part_number='TC427CPA', manufacturer='Microchip', identity_source='mouser',
        mouser_part_number='TC427CPA', mouser_package='PDIP-8', mouser_package_attribute='Package / Case'
    )
    apply_result(data, result, project_root=tmp_path, destination=tmp_path/'datasheets'/'TC427CPA.pdf')
    pkg=data['package']
    assert data['datasheet']['verified_exact_match'] is True
    assert pkg['value']=='PDIP-8'
    assert pkg['source']=='mouser'
    assert pkg['attribute_name']=='Package / Case'
    assert pkg['status']=='resolved'
    assert pkg['resolved_by']=='phase2'
    assert pkg['exact_part_number_match'] is True


def test_package_is_not_promoted_on_non_exact_match(tmp_path):
    data = {'part_number':'TC427CPA','datasheet':default_datasheet_state(),'package':{'value':None,'source':None,'attribute_name':None,'status':'unresolved','resolved_by':None,'exact_part_number_match':False,'sources_tried':[],'updated_at':None}}
    result = Result(
        part_number='TC427CPA', status='NOT_FOUND_CONFIRMED', matched_part_number='TC427CPA-ALT',
        manufacturer='Microchip', identity_source='mouser', mouser_part_number='TC427CPA-ALT',
        mouser_package='SOIC-8', mouser_package_attribute='Package / Case'
    )
    apply_result(data, result, project_root=tmp_path, destination=tmp_path/'datasheets'/'TC427CPA.pdf')
    assert data['datasheet']['verified_exact_match'] is False
    assert data['package']['value'] is None
    assert data['package']['status'] == 'unresolved'
