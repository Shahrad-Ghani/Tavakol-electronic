from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase2.metadata_state import apply_result, default_datasheet_state
from phase2.resolver_v43 import (
    Candidate,
    Result,
    SourceDebug,
    SOURCE_TRUE_NOT_FOUND,
    choose_candidate,
    exact,
    unresolved_final_status,
)


class Phase2ContractTests(unittest.TestCase):
    def test_exact_part_number_is_strict(self):
        self.assertTrue(exact("TBA130", "tba130"))
        self.assertFalse(exact("TBA130", "TBA130-2"))

    def test_trusted_selection_still_records_ambiguity(self):
        candidates = [
            Candidate("datasheet4u", "TBA800", "TBA800", "Fairchild", "u1"),
            Candidate("datasheet4u", "TBA800", "TBA800", "Telefunken", "u2"),
        ]
        selected, reason, _, canonical = choose_candidate(candidates, "Fairchild")
        self.assertIsNotNone(selected)
        self.assertTrue(reason.startswith("ambiguous_selected_trusted"))
        self.assertGreaterEqual(len(canonical), 2)

    def test_ambiguity_is_not_a_blocking_final_status(self):
        m = SourceDebug("TBA800", "mouser", SOURCE_TRUE_NOT_FOUND)
        d = SourceDebug("TBA800", "datasheet4u", SOURCE_TRUE_NOT_FOUND)
        a = SourceDebug("TBA800", "alldatasheet", SOURCE_TRUE_NOT_FOUND)
        status, _ = unresolved_final_status(m, d, a, identity_found=True, ambiguous=True)
        self.assertEqual(status, "IDENTITY_FOUND_DATASHEET_UNRESOLVED")

    def test_manufacturer_and_country_only_after_exact_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pdf = root / "datasheets" / "TC427CPA.pdf"
            pdf.parent.mkdir()
            pdf.write_bytes(b"%PDF-" + b"x" * 200)
            data = {"PartNumber": "TC427CPA", "status": {"datasheet": False}, "datasheet": default_datasheet_state()}
            result = Result(
                "TC427CPA", "DOWNLOADED", "TC427CPA", "Microchip",
                "mouser", "official:microchip", "https://example/pdf", str(pdf)
            )
            apply_result(data, result, project_root=root, destination=pdf)
            ds = data["datasheet"]
            self.assertTrue(ds["verified_exact_match"])
            self.assertEqual(ds["manufacturer"], "Microchip")
            self.assertEqual(ds["manufacturer_country"], "United States")
            self.assertEqual(ds["manufacturer_country_status"], "RESOLVED_REGISTRY")

    def test_nonexact_or_notfound_never_inherits_manufacturer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = {"PartNumber": "TBA130", "status": {"datasheet": False}, "datasheet": default_datasheet_state()}
            result = Result(
                "TBA130", "NOT_FOUND_CONFIRMED", "TBA130-2", "Siemens",
                "alldatasheet", "", "", ""
            )
            apply_result(data, result, project_root=root, destination=root / "datasheets/TBA130.pdf")
            ds = data["datasheet"]
            self.assertFalse(ds["verified_exact_match"])
            self.assertIsNone(ds["manufacturer"])
            self.assertIsNone(ds["manufacturer_country"])
            self.assertEqual(ds["identity_status"], "EXACT_PART_NUMBER_NOT_FOUND")
            self.assertEqual(ds["manufacturer_country_status"], "NOT_APPLICABLE_NO_EXACT_PART_NUMBER")


if __name__ == "__main__":
    unittest.main()
