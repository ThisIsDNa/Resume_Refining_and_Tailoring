"""Misfiled experience signals are logged; blocks pass through until segmentation is fixed."""

from __future__ import annotations

import unittest

from app.services.export_docx import (
    _experience_block_signals_misfiled_project_or_noise,
    _filter_misfiled_experience_blocks_for_docx,
    _rewrite_classification_gating_leak_in_blocks,
)


class TestMisfiledExperienceExportFilter(unittest.TestCase):
    def test_remote_only_company_signals_misfiled(self) -> None:
        b = {
            "company": "Remote",
            "title": "April",
            "bullets": ["Developed tools."],
        }
        self.assertTrue(_experience_block_signals_misfiled_project_or_noise(b))

    def test_month_only_role_signals_misfiled(self) -> None:
        b = {
            "company": "Some Corp",
            "title": "April",
            "bullets": ["Did work."],
        }
        self.assertTrue(_experience_block_signals_misfiled_project_or_noise(b))

    def test_project_phrase_in_bullets_signals_misfiled(self) -> None:
        b = {
            "company": "Acme",
            "title": "Engineer",
            "bullets": ["Implemented rule-based gating for QA flows."],
        }
        self.assertTrue(_experience_block_signals_misfiled_project_or_noise(b))

    def test_normal_gainwell_like_block_kept(self) -> None:
        b = {
            "company": "Gainwell Technologies",
            "title": "Senior Business Systems Analyst",
            "bullets": ["Led UAT for Provider Portal enrollment workflows."],
        }
        self.assertFalse(_experience_block_signals_misfiled_project_or_noise(b))

    def test_filter_keeps_all_rows_but_passes_through(self) -> None:
        good = {
            "company": "Gainwell Technologies",
            "title": "Senior BSA",
            "bullets": ["Owned validation."],
        }
        bad = {
            "company": "Remote",
            "title": "April",
            "bullets": ["Developed classification and rule-based gating."],
        }
        out = _filter_misfiled_experience_blocks_for_docx([good, bad])
        self.assertEqual(len(out), 2)
        self.assertIn("Gainwell", out[0]["company"])
        self.assertEqual(out[1]["company"], "Remote")

    def test_rewrite_classification_bullet(self) -> None:
        old = (
            "Developed classification and rule-based gating to ensure context-aware test generation "
            "and prevent cross-domain errors."
        )
        blocks = [
            {
                "company": "Acme",
                "title": "Engineer",
                "bullets": [old],
            }
        ]
        _rewrite_classification_gating_leak_in_blocks(blocks)
        self.assertNotIn("classification", blocks[0]["bullets"][0].lower())
        self.assertIn("route scenario types", blocks[0]["bullets"][0].lower())


if __name__ == "__main__":
    unittest.main()
