"""Stricter employer vs location / bucket line segmentation (resume_document_assembly)."""

from __future__ import annotations

import os
import unittest

from app.services import resume_document_assembly as rda


class TestSegmentationCompanyDetection(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("RESUME_TAILOR_SEGMENTATION_DEBUG", None)

    def test_city_state_not_employer_segment(self) -> None:
        self.assertFalse(rda._segment_looks_like_employer("San Mateo, CA"))
        self.assertFalse(rda._line_is_standalone_company_like("Sunnyvale, CA"))

    def test_year_only_not_employer(self) -> None:
        self.assertFalse(rda._segment_looks_like_employer("2026"))

    def test_skill_bucket_colon_not_employer(self) -> None:
        self.assertFalse(
            rda._segment_looks_like_employer("Systems & Platforms: Azure, Jira, Confluence")
        )

    def test_stakeholder_alignment_colon_not_employer(self) -> None:
        self.assertFalse(
            rda._segment_looks_like_employer(
                "Stakeholder Alignment: cross-functional planning and executive readouts"
            )
        )

    def test_gainwell_and_tesla_still_employers(self) -> None:
        self.assertTrue(rda._segment_looks_like_employer("Gainwell Technologies"))
        self.assertTrue(rda._segment_looks_like_employer("Tesla"))
        self.assertTrue(rda._segment_looks_like_employer("RWS Moravia (Client: Apple)"))

    def test_multiword_requires_org_signal(self) -> None:
        self.assertFalse(rda._segment_looks_like_employer("Acme Widgets Division"))

    def test_segmentation_debug_emits_when_enabled(self) -> None:
        os.environ["RESUME_TAILOR_SEGMENTATION_DEBUG"] = "1"
        rda._emit_segmentation_debug("San Mateo, CA", "location")


if __name__ == "__main__":
    unittest.main()
