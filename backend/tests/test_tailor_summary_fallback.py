"""Tailor API summary: weak generated text falls back to resume summary in output payload."""

from __future__ import annotations

import unittest

from app.services.output_builder import build_output_payload, is_weak_tailor_summary


class TestIsWeakTailorSummary(unittest.TestCase):
    def test_empty_is_weak(self) -> None:
        self.assertTrue(is_weak_tailor_summary(""))
        self.assertTrue(is_weak_tailor_summary("   "))

    def test_professional_with_experience_opener(self) -> None:
        self.assertTrue(
            is_weak_tailor_summary(
                "Professional with experience in excel, power bi, and python."
            )
        )

    def test_excel_power_bi_python_phrase(self) -> None:
        self.assertTrue(
            is_weak_tailor_summary(
                "Analyst with solid work in excel, power bi, and python for reporting."
            )
        )

    def test_minimal_lexicon_line(self) -> None:
        self.assertTrue(
            is_weak_tailor_summary(
                "Professional with experience in analysis, delivery, and documentation in professional settings."
            )
        )

    def test_strong_summary_not_weak(self) -> None:
        self.assertFalse(
            is_weak_tailor_summary(
                "Senior Business Systems Analyst leading UAT for enterprise provider portals, "
                "with measurable gains in release quality and stakeholder alignment."
            )
        )


class TestBuildOutputPayloadSummaryFallback(unittest.TestCase):
    def test_replaces_weak_tailored_with_original(self) -> None:
        resume_data = {
            "raw_text": "Jane Doe\njane@example.com",
            "sections": {
                "summary": [
                    "Senior Business Systems Analyst with UAT leadership across enterprise provider programs."
                ],
                "experience": [],
                "skills": ["SQL"],
            },
        }
        rewrite_result = {
            "tailored_summary": "Professional with experience in excel, power bi, and python.",
            "tailored_experience_bullets": [],
            "tailored_skills": [],
            "change_items": [
                {
                    "section": "summary",
                    "before": "old",
                    "after": "Professional with experience in excel, power bi, and python.",
                    "why": "test",
                    "company": None,
                }
            ],
        }
        raw = build_output_payload(
            resume_data,
            job_signals={},
            mapping_result={"rows": []},
            rewrite_result=rewrite_result,
            score_result={"overall_score": 70, "dimensions": {}, "summary": {}, "notes": []},
        )
        sections = raw["tailored_resume_sections"]
        self.assertIn("UAT", sections["summary"][0])
        self.assertNotIn("excel, power bi, and python", sections["summary"][0].lower())
        cb = raw["change_breakdown"]
        self.assertEqual(len(cb), 1)
        self.assertEqual(cb[0]["before"], cb[0]["after"])
        self.assertIn("Kept original summary", cb[0]["why"])

    def test_structured_changes_only_include_real_improvements(self) -> None:
        resume_data = {
            "raw_text": "Jane Doe\njane@example.com",
            "sections": {
                "summary": [
                    "Senior Business Systems Analyst with UAT leadership across enterprise provider programs."
                ],
                "experience": [],
                "skills": ["SQL"],
            },
        }
        rewrite_result = {
            "tailored_summary": "Senior Business Systems Analyst with UAT leadership across enterprise provider programs.",
            "tailored_experience_bullets": [],
            "tailored_skills": [],
            "change_items": [],
            "bullet_changes": [
                {
                    "evidence_id": "exp_1_bullet_1",
                    "section": "experience",
                    "before": "Worked with unclear processes.",
                    "after": "Designed structured validation workflows in ambiguous processes to improve consistency.",
                    "why": "Clarified impact and signal.",
                    "mode": "rewrite",
                },
                {
                    "evidence_id": "exp_1_bullet_2",
                    "section": "experience",
                    "before": "Kept same line.",
                    "after": "Kept same line.",
                    "why": "No change.",
                    "mode": "unchanged",
                },
            ],
        }
        mapping_result = {
            "requirement_matches": [
                {
                    "requirement_text": "Build structured validation frameworks",
                    "priority": "must_have",
                    "classification": "strong",
                    "matched_evidence": [{"id": "exp_1_bullet_1", "section": "experience"}],
                }
            ],
            "rows": [],
        }
        raw = build_output_payload(
            resume_data,
            job_signals={},
            mapping_result=mapping_result,
            rewrite_result=rewrite_result,
            score_result={"overall_score": 70, "dimensions": {}, "summary": {}, "notes": []},
        )
        changes = raw.get("structured_changes") or []
        self.assertEqual(len(changes), 1)
        self.assertNotEqual(changes[0]["before"], changes[0]["after"])
        self.assertIn(changes[0]["confidence"], ("high", "medium"))


if __name__ == "__main__":
    unittest.main()
