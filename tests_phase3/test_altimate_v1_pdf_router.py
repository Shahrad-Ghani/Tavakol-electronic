from pathlib import Path
from pypdf import PdfWriter
from phase3_fact_extraction.pipeline import FactExtractionPipeline

ROOT=Path(__file__).resolve().parents[1]
def make_test_pdf(tmp_path):
    """Create a tiny synthetic PDF; model calls are mocked in these tests."""
    path = tmp_path / 'TBB1469.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    with path.open('wb') as stream:
        writer.write(stream)
    return path

class FakeAgent:
    def __init__(self, model, result, fail_if_called=False):
        self.model=model; self.result=result; self.calls=0; self.fail_if_called=fail_if_called
    def run(self, pdf_path, instructions, payload, schema_name):
        self.calls += 1
        if self.fail_if_called:
            raise AssertionError('unexpected fallback PDF call')
        return self.result, {'provider':'openai','model':self.model,'usage':{'input_tokens':1000,'output_tokens':100}}


def fact(i,param,section='ELECTRICAL_CHARACTERISTIC',value='1',unit=None):
    return {'id':f'f{i}','parameter':param,'claim':f'{param} = {value} {unit or ""}'.strip(),'value_text':value,'unit':unit,'condition':None,'section':section,'scope':'TARGET_ONLY','seo_usage':'NORMAL','page':1}


def result(facts, exact=True):
    return {'source_assessment':{'exact_part_number_covered':exact,'source_kind':'DATASHEET','manufacturer':'Siemens','reason':'visible exact PN'},'facts':facts}


def cfg():
    return {
        'pdf_primary_model':'gpt-5.6-luna','pdf_max_output_tokens':1000,'pdf_reasoning_effort':'low','pdf_first_pages':5,'fact_extraction_max_facts':16,
        'fact_coverage':{'minimum_useful_facts':5,'minimum_priority_categories':3,'alternative_useful_facts':8,'priority_categories':['voltage','current','package','application_or_function','frequency','operating_temperature']}
    }


def sufficient_facts():
    return [
        fact(1,'Operating supply voltage','OPERATING_CONDITION','12','V'),
        fact(2,'Supply current','ELECTRICAL_CHARACTERISTIC','4','mA'),
        fact(3,'Package','PACKAGE','P-DIP-16',None),
        fact(4,'RF gain','ELECTRICAL_CHARACTERISTIC','42','dB'),
        fact(5,'Audio bandwidth','ELECTRICAL_CHARACTERISTIC','35','kHz'),
    ]


def test_normal_path_is_exactly_one_luna_pdf_call(tmp_path):
    primary=FakeAgent('gpt-5.6-luna',result(sufficient_facts()))
    fallback=FakeAgent('unused-fallback',result([]),fail_if_called=True)
    p=FactExtractionPipeline(ROOT,cfg(),primary_agent=primary,fallback_agent=fallback,file_manager=object())
    out=p.process('TBB1469',make_test_pdf(tmp_path),tmp_path/'work',force=True)
    assert primary.calls==1
    assert fallback.calls==0
    assert out['source_validation']['pdf_calls']==1
    assert out['source_validation']['fallback_used'] is False
    assert out['facts']['extraction']['pdf_closed_after_stage'] is True


def test_sparse_primary_is_retained_without_second_pdf_call(tmp_path):
    primary=FakeAgent('gpt-5.6-luna',result([fact(1,'Supply current',value='4',unit='mA')]))
    fallback=FakeAgent('unused-fallback',result([]),fail_if_called=True)
    p=FactExtractionPipeline(ROOT,cfg(),primary_agent=primary,fallback_agent=fallback,file_manager=object())
    out=p.process('TBB1469',make_test_pdf(tmp_path),tmp_path/'work',force=True)
    assert primary.calls==1 and fallback.calls==0
    assert out['source_validation']['pdf_calls']==1
    assert out['source_validation']['fallback_used'] is False
    assert out['fallback_path'] is None
    assert out['coverage']['sufficient'] is False
    assert out['facts']['useful_fact_count']==1
    assert out['facts']['fact_status']=='INSUFFICIENT'


def test_truncated_five_page_window_does_not_change_source_kind(tmp_path):
    primary=FakeAgent('gpt-5.6-luna',result(sufficient_facts()))
    fallback=FakeAgent('unused-fallback',result([]),fail_if_called=True)
    c=cfg(); c['pdf_first_pages']=1
    p=FactExtractionPipeline(ROOT,c,primary_agent=primary,fallback_agent=fallback,file_manager=object())
    out=p.process('TBB1469',make_test_pdf(tmp_path),tmp_path/'work',force=True)
    assert out['pdf_window']['truncated'] is True
    assert out['source_validation']['source_kind']=='DATASHEET'
    assert out['source_validation']['original_source_status']=='EXACT_DATASHEET_FILE_RESOLVED_BY_PHASE2'
