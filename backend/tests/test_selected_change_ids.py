"""Multipart ``selected_change_ids`` JSON parsing for export routes (plumbing only)."""

from __future__ import annotations

import copy
import unittest

from app.services.export_docx import DOCX_EXPORT_VALIDATION_SUCCESS, build_export_docx_package
from app.services.gap_analysis import analyze_resume_gap_report
from app.services.refinery_transform import apply_refinery_actions, build_refinery_export_shims
from app.utils.selected_change_ids import parse_selected_change_ids

from test_refinery_export import _rich_resume_fixture


class TestParseSelectedChangeIds(unittest.TestCase):
    def test_missing_none_returns_empty(self) -> None:
        self.assertEqual(parse_selected_change_ids(None), [])

    def test_missing_blank_returns_empty(self) -> None:
        self.assertEqual(parse_selected_change_ids(""), [])
        self.assertEqual(parse_selected_change_ids("   "), [])

    def test_invalid_json_returns_empty(self) -> None:
        self.assertEqual(parse_selected_change_ids("{"), [])
        self.assertEqual(parse_selected_change_ids("not json"), [])

    def test_non_list_json_returns_empty(self) -> None:
        self.assertEqual(parse_selected_change_ids("{}"), [])
        self.assertEqual(parse_selected_change_ids('"x"'), [])
        self.assertEqual(parse_selected_change_ids("42"), [])

    def test_mixed_list_filters_to_strings_only(self) -> None:
        self.assertEqual(
            parse_selected_change_ids('["a", 1, null, "b", {}, "  "]'),
            ["a", "b"],
        )

    def test_dedupe_preserves_order(self) -> None:
        self.assertEqual(
            parse_selected_change_ids('["x", "y", "x", "z", "y"]'),
            ["x", "y", "z"],
        )

    def test_strips_and_drops_empty_strings(self) -> None:
        self.assertEqual(
            parse_selected_change_ids('["  a  ", "", "  ", "b"]'),
            ["a", "b"],
        )

    def test_valid_json_array_of_strings(self) -> None:
        self.assertEqual(parse_selected_change_ids('["a", "b"]'), ["a", "b"])
        self.assertEqual(parse_selected_change_ids("[]"), [])


class TestBuildExportWithSelectedChangeIds(unittest.TestCase):
    """Export package accepts optional selection plumbing without changing DOCX outcome."""

    def test_build_export_docx_package_with_selected_ids(self) -> None:
        resume = _rich_resume_fixture()
        gap = analyze_resume_gap_report(resume, "product_analyst", job_description="")
        refined = apply_refinery_actions(copy.deepcopy(resume), gap)
        rewrite_result, score_result, mapping_result, job_signals = build_refinery_export_shims(refined)
        docx_bytes, _fn, err, ok = build_export_docx_package(
            refined,
            rewrite_result,
            score_result,
            mapping_result,
            job_signals,
            refinery_experience_spacing=True,
            selected_change_ids=["tailor-bullet-1", "tailor-bullet-1", "x"],
            export_route_label="test",
        )
        self.assertFalse(err, msg=err)
        self.assertEqual(ok, DOCX_EXPORT_VALIDATION_SUCCESS)
        self.assertGreater(len(docx_bytes), 2000)

    def test_build_export_docx_package_without_selected_ids_unchanged(self) -> None:
        resume = _rich_resume_fixture()
        gap = analyze_resume_gap_report(resume, "product_analyst", job_description="")
        refined = apply_refinery_actions(copy.deepcopy(resume), gap)
        rewrite_result, score_result, mapping_result, job_signals = build_refinery_export_shims(refined)
        docx_bytes, _fn, err, ok = build_export_docx_package(
            refined,
            rewrite_result,
            score_result,
            mapping_result,
            job_signals,
            refinery_experience_spacing=True,
        )
        self.assertFalse(err, msg=err)
        self.assertEqual(ok, DOCX_EXPORT_VALIDATION_SUCCESS)
        self.assertGreater(len(docx_bytes), 2000)


if __name__ == "__main__":
    unittest.main()
