from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from metadata_manager import _new_record, _normalize_integrated_identity, save
from phase2.metadata_state import apply_result, default_datasheet_state, ensure_phase2_shape
from phase2.resolver_v43 import Result, exact

ROOT = Path(__file__).resolve().parents[1]

class IntegratedContractTests(unittest.TestCase):
    def test_schema_accepts_new_record(self):
        schema=json.loads((ROOT/'metadata_schema.json').read_text(encoding='utf-8'))
        data=_new_record('IMG_TEST','IC')
        Draft202012Validator(schema).validate(data)

    def test_legacy_ocr_identity_is_not_canonical(self):
        data=_new_record('IMG_TEST','IC')
        data['manufacturer']='TFK'
        data['country']='Germany'
        _normalize_integrated_identity(data)
        self.assertIsNone(data['manufacturer'])
        self.assertIsNone(data['country'])
        self.assertEqual(data['ocr']['manufacturer_marking'],'TFK')
        self.assertEqual(data['ocr']['country_marking'],'Germany')

    def test_exact_phase2_promotes_canonical_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            pdf=root/'datasheets'/'TC427CPA.pdf'; pdf.parent.mkdir(); pdf.write_bytes(b'%PDF-'+b'x'*200)
            data=_new_record('IMG_TEST','IC'); data['PartNumber']='TC427CPA'
            result=Result('TC427CPA','DOWNLOADED','TC427CPA','Microchip','mouser','official:microchip','https://example/pdf',str(pdf))
            apply_result(data,result,project_root=root,destination=pdf)
            self.assertTrue(data['datasheet']['verified_exact_match'])
            self.assertEqual(data['manufacturer'],'Microchip')
            self.assertEqual(data['country'],'United States')

    def test_near_part_never_promotes_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            data=_new_record('IMG_TEST','IC'); data['PartNumber']='TBA130'
            result=Result('TBA130','NOT_FOUND_CONFIRMED','TBA130-2','Siemens','alldatasheet','','','')
            apply_result(data,result,project_root=root,destination=root/'datasheets/TBA130.pdf')
            self.assertFalse(data['datasheet']['verified_exact_match'])
            self.assertIsNone(data['manufacturer']); self.assertIsNone(data['country'])
            self.assertEqual(data['datasheet']['identity_status'],'EXACT_PART_NUMBER_NOT_FOUND')

    def test_coordinator_drains_at_ten_and_flushes_remainder(self):
        from phase2.coordinator import Phase2Coordinator
        class FakePipeline:
            def __init__(self): self.batches=[]
            def eligible_paths(self, paths=None): return list(paths or [])
            def process_batch(self, paths):
                self.batches.append(list(paths)); return len(paths)
        fake=FakePipeline(); c=Phase2Coordinator(fake)
        for i in range(13):
            c.enqueue(Path(f"/tmp/meta_{i}.json"))
        self.assertEqual([len(x) for x in fake.batches],[10])
        self.assertEqual(c.flush(),3)
        self.assertEqual([len(x) for x in fake.batches],[10,3])

if __name__=='__main__': unittest.main()
