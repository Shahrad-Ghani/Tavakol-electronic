from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys
import types

from PIL import Image, ImageDraw

# Keep the contract test runnable in minimal CI environments where the real
# OpenAI package is not installed; production installs it from requirements.txt.
if "openai" not in sys.modules:
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = object
    sys.modules["openai"] = fake_openai

from ocr import extract, OCR_PROMPT_VERSION


class _FakeResponses:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return SimpleNamespace(
            status="completed",
            output_text=json.dumps(payload),
            usage=None,
        )


class _FakeClient:
    def __init__(self, payloads):
        self.responses = _FakeResponses(payloads)


def _base_payload(**overrides):
    payload = {
        "PartNumber": "TB6560AFTG",
        "manufacturer": "Toshiba",
        "country": "JAPAN",
        "visible_lines_original": ["TB", "6560AFTG", "242GA+1", "JAPAN"],
        "visible_lines_regenerated": ["T8", "6560AFTG", "242GA41", "JAPAN"],
        "visible_lines": ["TB", "6560AFTG", "242GA+1", "JAPAN"],
        "primary_code": "TB6560AFTG",
        "part_number_segments": ["TB", "6560AFTG"],
        "part_number_layout": "multi_line",
        "part_number_confidence": "high",
        "image_source_decision": "original_dominant",
        "secondary_codes": ["242GA+1", "JAPAN"],
        "comparison_conflicts": ["Original TB vs regenerated T8; chose original B over 8."],
        "candidate_part_numbers": [
            {"value": "TB6560AFTG", "confidence": 0.97, "reason": "Original image supports B, not 8."},
            {"value": "T86560AFTG", "confidence": 0.21, "reason": "Generated image distortion."},
        ],
        "selected_candidate_reason": "Original image supports TB + 6560AFTG as one device identifier.",
        "critical_character_review": ["Reviewed B vs 8 using original image; selected B."],
        "notes": "Original image resolves the B/8 conflict.",
    }
    payload.update(overrides)
    return payload


class DualImageOCRContractTests(unittest.TestCase):
    def _images(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        original = root / "original.jpg"
        regenerated = root / "regen.webp"

        for path, bg in [(original, (235, 235, 235)), (regenerated, (255, 255, 255))]:
            im = Image.new("RGB", (700, 900), bg)
            draw = ImageDraw.Draw(im)
            draw.rectangle((170, 160, 530, 620), fill=(35, 35, 35))
            draw.rectangle((235, 250, 465, 470), fill=(55, 55, 55))
            im.save(path)
        return td, original, regenerated

    def test_prompt_version_is_v4(self):
        self.assertEqual(OCR_PROMPT_VERSION, "v4.0-dual-image-cropped-fallback-ocr")

    def test_one_request_contains_two_images_and_uses_detail_original(self):
        td, original, regenerated = self._images()
        try:
            client = _FakeClient([_base_payload(comparison_conflicts=[], critical_character_review=[] )])
            result = extract(client, original, regenerated)
            self.assertEqual(len(client.responses.calls), 1)
            content = client.responses.calls[0]["input"][0]["content"]
            images = [item for item in content if item.get("type") == "input_image"]
            self.assertEqual(len(images), 2)
            self.assertTrue(all(img.get("detail") == "original" for img in images))
            self.assertEqual(result["PartNumber"], "TB6560AFTG")
            self.assertEqual(result["part_number_segments"], ["TB", "6560AFTG"])
            self.assertEqual(result["image_source_decision"], "original_dominant")
            self.assertEqual(result["_ocr_view_mode"], "dual-image-cropped-upscaled")
        finally:
            td.cleanup()

    def test_low_confidence_primary_triggers_fallback(self):
        td, original, regenerated = self._images()
        try:
            client = _FakeClient([
                _base_payload(PartNumber=None, primary_code=None, part_number_confidence="low", image_source_decision="uncertain"),
                _base_payload(),
            ])
            result = extract(client, original, regenerated)
            self.assertEqual(len(client.responses.calls), 2)
            self.assertEqual(result["PartNumber"], "TB6560AFTG")
            self.assertTrue(result["_fallback_used"])
            self.assertEqual(result["_model_used"], "gpt-5.6-sol")
        finally:
            td.cleanup()

    def test_model_disagreement_blocks_partnumber(self):
        td, original, regenerated = self._images()
        try:
            client = _FakeClient([
                _base_payload(),
                _base_payload(PartNumber="T86560AFTG", primary_code="T86560AFTG", selected_candidate_reason="Generated image seems to show 8."),
            ])
            result = extract(client, original, regenerated)
            self.assertEqual(len(client.responses.calls), 2)
            self.assertIsNone(result["PartNumber"])
            self.assertEqual(result["part_number_confidence"], "low")
            self.assertTrue(any("disagreed" in x for x in result["comparison_conflicts"]))
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
