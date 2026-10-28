"""V4.0.6 offline regression coverage; no live WordPress writes."""
import hashlib
import inspect
import json
from pathlib import Path
from unittest.mock import Mock

from pypdf import PdfWriter

import phase4.publisher as publisher
from phase4.publisher_state import PublisherStateStore
from metadata_manager import load_or_create, save
from admin_audit import attach_manual_datasheet
from run_ui import can_attach_manual_datasheet


def _bundle():
    return publisher.ProductBundle(
        pn='TEST406', title='ماسفت TEST406', package=None,
        html_path=Path('product.html'), html='<p>content</p>',
        short_description_html='short', image_path=Path('test.webp'),
        datasheet_path=None, datasheet_status='not_found_confirmed',
        product_json_path=Path('product.json'), category_key='mosfet',
        category_parent='قطعات الکترونیکی', category_child='ماسفت',
        category_parent_term_id=110, category_term_id=115,
        slug='test406-mosfet', seo_title='خرید ماسفت TEST406',
        meta_description='meta', mosfet_specs={},
    )


def test_attribute_entry_does_not_click_ajax_save(monkeypatch):
    bundle = _bundle()
    field_values = {'name': '', 'value': ''}
    class Field:
        def __init__(self, which): self.which=which
        def fill(self, value): field_values[self.which]=value
        def input_value(self): return field_values[self.which]
        def press(self, key): pass
    class Row:
        def locator(self, selector):
            return Field('name' if selector == 'input.attribute_name' else 'value')
    class Rows:
        def count(self): return 1
        def nth(self, i): assert i==0; return Row()
    class Page:
        def locator(self, selector):
            if 'save_attributes' in selector:
                raise AssertionError('save_attributes must not be looked up or clicked')
            if selector == '#product_attributes .product_attributes .woocommerce_attribute': return Rows()
            raise AssertionError(f'unexpected selector: {selector}')
    tab=Mock()
    monkeypatch.setattr(publisher, 'close_media_modal_if_open', lambda page: None)
    monkeypatch.setattr(publisher, 'wait_for_woocommerce_unblocked', lambda page, **k: None)
    monkeypatch.setattr(publisher, 'first_visible', lambda page, selectors, **k: tab)
    monkeypatch.setattr(publisher, 'dispatch_value_events', lambda field: None)
    publisher.set_attributes(Page(), bundle)
    assert field_values == {'name': 'Part Number', 'value': 'TEST406'}


def test_category_does_not_reclick_already_active_tab(monkeypatch):
    bundle=_bundle()
    checked={110:False,115:False}
    class Checkbox:
        def __init__(self,tid): self.tid=tid
        def is_checked(self): return checked[self.tid]
        def check(self,**kwargs): checked[self.tid]=True
    class Checklist:
        def count(self): return 1
        def is_visible(self): return True
    class Box:
        def count(self): return 1
    class Page:
        def locator(self, selector):
            if selector=='#product_catchecklist': return Checklist()
            if selector=='#product_catdiv': return Box()
            if selector.startswith('#product_cat-tabs'):
                raise AssertionError('Already active All Categories tab should not be clicked')
            raise AssertionError(selector)
    monkeypatch.setattr(publisher,'close_media_modal_if_open',lambda page:None)
    monkeypatch.setattr(publisher,'wait_for_woocommerce_unblocked',lambda page, **k:None)
    monkeypatch.setattr(publisher,'_category_checkbox',lambda page,tid,label,**k:Checkbox(tid))
    publisher.set_product_category(Page(),bundle)
    assert all(checked.values())


def test_save_draft_attempted_even_with_failed_individual_step(tmp_path,monkeypatch):
    """Warn with the saved WordPress ID; NEVER report full success or retry duplicate."""
    bundle=_bundle()
    store=PublisherStateStore(tmp_path)
    monkeypatch.setattr(publisher,'RUNTIME_ROOT',tmp_path)
    monkeypatch.setattr(publisher,'locate_existing_wordpress_product',lambda page,bundle:None)
    monkeypatch.setattr(publisher,'open_new_product',lambda page,pn:None)
    monkeypatch.setattr(publisher,'_category_checkbox',lambda *a,**k:object())
    monkeypatch.setattr(publisher,'sync_publisher_summary_to_metadata',lambda *a,**k:None)
    monkeypatch.setattr(publisher,'capture_debug',lambda *a,**k:None)
    monkeypatch.setattr(publisher,'recover_ui_after_step_error',lambda *a,**k:None)
    calls=[]
    def failed_image(*args): raise RuntimeError('image upload failed')
    monkeypatch.setattr(publisher,'upload_product_image',failed_image)
    for name in ['set_title_and_main_content','upload_datasheet','set_attributes',
                 'set_sku','set_product_category','set_short_description',
                 'set_rankmath_snippet','set_focus_keyword']:
        monkeypatch.setattr(publisher,name,lambda *a:None)
    def saved(*args): calls.append('save_draft'); return ('990','https://example.test/wp-admin/post.php?post=990&action=edit')
    monkeypatch.setattr(publisher,'save_draft',saved)
    result=publisher.publish_one(object(),bundle,store)
    state=store.load('TEST406')
    assert calls == ['save_draft']
    assert result.status == 'WP_DRAFT_SAVED_WITH_WARNINGS'
    assert result.wordpress_product_id == '990'
    assert state['status']=='DRAFT_SAVED_WITH_WARNINGS'
    assert state['successful'] is False
    assert state['steps']['image']['status']=='failed'
    assert state['steps']['save_draft']['status']=='success'
    assert store.duplicate_guard('TEST406')[0] is True


def test_failed_datasheet_is_attachable_and_reprocesses_facts_seo(tmp_path):
    assert can_attach_manual_datasheet('2SK18','failed')
    assert not can_attach_manual_datasheet('', 'failed')
    assert not can_attach_manual_datasheet('2SK18','completed')
    meta,data=load_or_create(tmp_path,'2SK18')
    data['part_number']='2SK18'
    data['datasheet']['status']='failed'
    save(meta,data)
    source=tmp_path/'manual.pdf'
    pdf=PdfWriter();pdf.add_blank_page(width=612,height=792)
    with source.open('wb') as f:pdf.write(f)
    result=attach_manual_datasheet(tmp_path,meta,source)
    stored=json.loads(meta.read_text('utf8'))
    assert result['status']=='MANUAL_DATASHEET_ATTACHED'
    assert (tmp_path/'datasheets/2SK18.pdf').is_file()
    assert stored['datasheet']['status']=='completed'
    assert stored['admin_audit']['force_fact_extraction'] is True
    assert stored['admin_audit']['force_seo'] is True
    assert stored['admin_audit']['force_phase2'] is False
    assert stored['admin_audit']['status']=='DISAPPROVED_PENDING_REPROCESS'


def test_duplicate_guard_code_unchanged_from_405():
    # Enforce user's hard boundary at the source level (same method as V4.0.5).
    source = inspect.getsource(PublisherStateStore.duplicate_guard)
    expected_sha256 = '219269a0ab952b2472d78fb51ffc7ec606c44c36ba503b8e5b0cbf07ff3ea3af'
    assert hashlib.sha256(source.encode()).hexdigest() == expected_sha256


def test_save_draft_waits_for_ajax_and_uses_only_draft_button(monkeypatch):
    calls=[]
    bundle=_bundle()
    class SaveButton:
        def is_enabled(self):return True
        def click(self,**kwargs):calls.append('click_save_post')
    class Title:
        def count(self):return 1
        def input_value(self):return bundle.title
    class Page:
        url='https://example.test/wp-admin/post.php?post=990&action=edit'
        def locator(self,sel):
            assert sel=='#title', f'Unexpected selector {sel}'
            return Title()
        def wait_for_function(self,*a,**k):calls.append('wait_for_post_id')
        def wait_for_timeout(self,*a):pass
    monkeypatch.setattr(publisher,'close_media_modal_if_open',lambda page:calls.append('close_modal'))
    monkeypatch.setattr(publisher,'wait_for_woocommerce_unblocked',lambda page,timeout_ms=0:calls.append('wait_for_ajax'))
    def find_button(page,selectors):
        assert selectors==['#save-post:visible']
        return SaveButton()
    monkeypatch.setattr(publisher,'first_visible',find_button)
    monkeypatch.setattr(publisher,'verify_saved_draft',lambda page,bundle:[])
    monkeypatch.setattr(publisher,'wait_ms',lambda *a,**k:None)
    result=publisher.save_draft(Page(),bundle)
    assert result[0]=='990'
    assert calls==['close_modal','wait_for_ajax','click_save_post','wait_for_post_id']


def test_hidden_category_tab_switched_only_when_needed():
    class Checklist:
        def __init__(self):self.visible=False
        def count(self):return 1
        def is_visible(self):return self.visible
    checklist=Checklist()
    class Tab:
        def count(self):return 1
        @property
        def first(self):return self
        def scroll_into_view_if_needed(self,**kwargs):pass
        def click(self,**kwargs):checklist.visible=True
    class Page:
        def locator(self,sel):
            return checklist if sel=='#product_catchecklist' else Tab()
    publisher._show_all_product_categories(Page())
    assert checklist.visible
