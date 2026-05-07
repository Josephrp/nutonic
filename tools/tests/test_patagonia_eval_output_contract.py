"""Tests for the hard output-contract scorer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_output_contract import output_contract_score  # noqa: E402


_VALID_CAPTION = (
    "Sentinel-2 imagery shows a temperate Andean lake bordered by dense forest with bare-rock ridgelines to the north. "
    "Optical interpretation only.\n\n"
    "```json\n"
    "{\"boxes\": [{\"label\": \"water\", \"bbox\": [0.10, 0.20, 0.55, 0.70], \"confidence\": 0.7}]}\n"
    "```"
)

_VALID_EMPTY_BOXES = (
    "Open ocean tile with no land features visible. Optical-only chip; absence of vessels not asserted.\n\n"
    "```json\n{\"boxes\": []}\n```"
)


class TestOutputContract(unittest.TestCase):
    def test_clean_caption_with_one_box_scores_one(self) -> None:
        s, b = output_contract_score(_VALID_CAPTION)
        self.assertEqual(s, 1.0, b)
        self.assertEqual(b["n_boxes"], 1)
        self.assertEqual(b["verdict"], "ok")

    def test_empty_boxes_array_is_valid(self) -> None:
        s, b = output_contract_score(_VALID_EMPTY_BOXES)
        self.assertEqual(s, 1.0, b)
        self.assertEqual(b["n_boxes"], 0)

    def test_finetune_zero_box_literal_is_zero(self) -> None:
        cap = "[x1=0.0, y1=0.0, x2=0.0, y2=0.0]\n\nLand-use change flags: cropland ~20%, tree cover ~20%."
        s, b = output_contract_score(cap)
        self.assertEqual(s, 0.0, b)
        self.assertIn("xy_eq_zero_literal", b["leaks"])

    def test_captions_marker_leak_is_zero(self) -> None:
        cap = '[captions: "Sentinel-2 imagery shows dominant cropland"; [boxes] []'
        s, b = output_contract_score(cap)
        self.assertEqual(s, 0.0, b)
        self.assertIn("captions_marker", b["leaks"])

    def test_no_fenced_block_when_caption_empty_is_zero(self) -> None:
        cap = "Just a free-text caption with no JSON tail at all."
        s, b = output_contract_score(cap)
        self.assertEqual(s, 0.0, b)
        self.assertEqual(b["verdict"], "no_fenced_block")

    def test_unparseable_fenced_block_scores_partial(self) -> None:
        cap = "Caption preamble.\n\n```json\n{not valid json}\n```"
        s, b = output_contract_score(cap)
        self.assertEqual(s, 0.4, b)
        self.assertTrue(b["json_parse_error"].startswith("json_decode_error"), b)

    def test_schema_invalid_when_bbox_out_of_range(self) -> None:
        cap = (
            "Caption preamble describing the scene.\n\n"
            "```json\n"
            "{\"boxes\": [{\"label\": \"water\", \"bbox\": [0.0, 0.0, 1.5, 1.0]}]}\n"
            "```"
        )
        s, b = output_contract_score(cap)
        self.assertEqual(s, 0.6, b)
        self.assertEqual(b["schema_error"], "box_0_bbox_range")

    def test_short_preamble_scores_eight_tenths(self) -> None:
        cap = "Short. \n\n```json\n{\"boxes\": []}\n```"
        s, b = output_contract_score(cap, min_caption_words=12)
        self.assertEqual(s, 0.8, b)
        self.assertEqual(b["verdict"], "preamble_too_short")

    def test_schema_rejects_missing_boxes_key(self) -> None:
        cap = (
            "Caption preamble describing the scene with enough words to pass the preamble gate.\n\n"
            "```json\n{\"summary\": \"no boxes key here\"}\n```"
        )
        s, b = output_contract_score(cap)
        self.assertEqual(s, 0.6, b)
        self.assertEqual(b["schema_error"], "missing_boxes_key")

    def test_schema_rejects_disordered_bbox(self) -> None:
        cap = (
            "Caption preamble describing the scene with enough words for the gate.\n\n"
            "```json\n"
            "{\"boxes\": [{\"label\": \"forest\", \"bbox\": [0.5, 0.5, 0.4, 0.6]}]}\n"
            "```"
        )
        s, b = output_contract_score(cap)
        self.assertEqual(s, 0.6, b)
        self.assertEqual(b["schema_error"], "box_0_bbox_order")


if __name__ == "__main__":
    unittest.main()
