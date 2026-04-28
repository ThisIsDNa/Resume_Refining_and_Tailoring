"""Tests for DOCX export summary selection (no validation weakening)."""

from __future__ import annotations

import os
import unittest

from app.services import export_docx as ed


class TestExportSummaryFallback(unittest.TestCase):
    def test_role_led_bsa_requirements_efficiency_pair_not_banned(self) -> None:
        """Role-led outcome summaries must not be banned; they can beat ``minimal_lexicon``."""
        self.assertFalse(
            ed._is_banned_strongest_summary_pattern(
                "Business Systems Analyst with experience in business requirements and operational efficiency."
            )
        )

    def test_banned_weak_bsa_documentation_validation_reporting(self) -> None:
        self.assertTrue(
            ed._is_banned_strongest_summary_pattern(
                "Business Systems Analyst with experience in documentation, validation, and reporting."
            )
        )

    def setUp(self) -> None:
        self._prev_fallback = os.environ.get(ed._EXPORT_FALLBACK_ONLY_ENV)

    def tearDown(self) -> None:
        if self._prev_fallback is None:
            os.environ.pop(ed._EXPORT_FALLBACK_ONLY_ENV, None)
        else:
            os.environ[ed._EXPORT_FALLBACK_ONLY_ENV] = self._prev_fallback

    def test_fallback_nonempty_one_sentence(self) -> None:
        corpus = (
            "business analyst data analysis testing reporting validation "
            "documentation professional experience analysis delivery settings"
        )
        resume_blob = (
            "Business Analyst with data analysis, testing, reporting, and validation experience."
        )
        s = ed.build_resume_grounded_export_summary(
            resume_blob,
            None,
            corpus_for_validation=corpus,
            match_strength="medium",
        )
        self.assertTrue(s.strip())
        self.assertEqual(s.count("."), 1, msg=s)

    def test_fallback_passes_export_hygiene_with_rich_corpus(self) -> None:
        corpus = (
            "business analyst data analysis testing reporting validation documentation "
            "professional experience analysis delivery documentation settings "
            "user acceptance testing process improvement"
        )
        resume_blob = (
            "Business Analyst with data analysis, user acceptance testing, "
            "process improvement, reporting, and validation."
        )
        s = ed.build_resume_grounded_export_summary(
            resume_blob,
            None,
            corpus_for_validation=corpus,
            match_strength="strong",
        )
        self.assertTrue(
            ed._export_summary_passes_hygiene(s, corpus, "strong"),
            msg=s,
        )

    def test_choose_falls_back_when_tailored_ungrounded(self) -> None:
        resume_data = {
            "raw_text": (
                "Business Analyst with data analysis, testing, reporting, and documentation."
            ),
            "sections": {},
        }
        grounding = (
            resume_data["raw_text"]
            + " "
            + "business analyst data analysis testing reporting documentation professional"
        )
        s, src = ed.strongest_summary_from_resume(
            "SynergyVision Blockchain QuantumLeap orchestration platform",
            "medium",
            resume_data,
            grounding,
        )
        self.assertIn(
            src,
            (
                "fallback",
                "resume_fallback",
                "identity_forward_dense",
                "identity_structured",
                "outcome_phrase",
                "outcome_phrase_relaxed",
                "outcome_phrase_role_priority",
                "last_resort",
            ),
        )
        self.assertNotIn("SynergyVision", s)

    def test_identity_structured_summary_when_tailored_missing(self) -> None:
        resume_data = {
            "raw_text": (
                "Senior Business Systems Analyst with user acceptance testing and "
                "regulatory compliance in enterprise programs."
            ),
            "sections": {
                "experience": [
                    {
                        "company": "Gainwell Technologies",
                        "title": "Senior Business Systems Analyst / Senior UAT Lead",
                        "date_range": "2024 - Present",
                        "location": "Remote",
                        "bullets": ["Led UAT cycles for claims module."],
                    }
                ]
            },
        }
        grounding = (
            resume_data["raw_text"]
            + " user acceptance testing regulatory compliance enterprise cross-functional uat lead"
        )
        s, src = ed.strongest_summary_from_resume("", "medium", resume_data, grounding)
        self.assertIn(
            src,
            ("identity_forward_dense", "identity_structured"),
            msg=f"unexpected src={src}: {s!r}",
        )
        self.assertIn("Senior Business Systems Analyst", s)
        self.assertTrue(
            ed._export_summary_passes_hygiene(s, grounding, "medium"),
            msg=s,
        )

    def test_choose_uses_tailored_when_valid(self) -> None:
        resume_data = {"raw_text": "Business analyst with analysis and reporting.", "sections": {}}
        grounding = (
            resume_data["raw_text"]
            + " business analyst analysis reporting documentation professional experience"
        )
        ok = "Business analyst with experience in analysis and reporting."
        self.assertTrue(
            ed._export_summary_passes_hygiene(ok, grounding, "medium"),
            msg="fixture must be valid for this test",
        )
        s, src = ed.strongest_summary_from_resume(ok, "medium", resume_data, grounding)
        self.assertEqual(src, "tailored")
        self.assertEqual(s, ok)

    def test_step1_still_fails_on_unrelated_issues(self) -> None:
        """Validation is not bypassed: non-summary failures can still block export."""
        resume_data = {"raw_text": "x", "sections": {}}
        grounding = "business analyst analysis reporting documentation professional experience"
        summary = ed._MINIMAL_LEXICON_SUMMARY
        self.assertTrue(
            ed._export_summary_passes_hygiene(summary, grounding, "medium"),
        )
        bad_exp = [
            {
                "title": "Role",
                "company": "Co",
                "bullets": ["coaching: ignored"],
            }
        ]
        failures = ed.validate_export_pre_docx(
            summary=summary,
            experience_merged=bad_exp,
            match_strength="medium",
            resume_data=resume_data,
            experience_original=bad_exp,
            bullet_changes=[],
        )
        self.assertTrue(failures)


if __name__ == "__main__":
    unittest.main()
