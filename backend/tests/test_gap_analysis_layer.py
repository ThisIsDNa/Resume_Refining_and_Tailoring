"""Gap analysis: signal extraction, role templates, and gap engine (no DOCX)."""

from __future__ import annotations

import unittest

from app.services.gap_analysis import (
    analyze_resume_gap_report,
    extract_resume_signals,
    list_role_template_ids,
)
from app.services.gap_analysis.role_templates import get_role_profile


class TestSignalExtractor(unittest.TestCase):
    def test_extract_tools_and_evidence_from_sections(self) -> None:
        resume = {
            "sections": {
                "summary": ["Product analyst focused on experimentation."],
                "experience": [
                    {
                        "company": "Acme",
                        "title": "Analyst",
                        "bullets": [
                            "Built SQL queries to validate funnel metrics and dashboards for leadership.",
                        ],
                    }
                ],
                "skills": ["SQL", "Python", "Excel"],
                "projects": [],
            }
        }
        out = extract_resume_signals(resume)
        self.assertIn("sql", out["tools"])
        self.assertTrue(out["strengths"] or out["evidence_signals"])
        ids = {e["signal_id"] for e in out["evidence_signals"]}
        self.assertIn("sql_data", ids)

    def test_empty_resume_returns_empty_signals(self) -> None:
        self.assertEqual(
            extract_resume_signals({}),
            {"strengths": [], "tools": [], "evidence_signals": []},
        )


class TestRoleTemplates(unittest.TestCase):
    def test_list_ids_stable(self) -> None:
        ids = list_role_template_ids()
        self.assertIn("product_analyst", ids)
        self.assertIn("bizops", ids)
        self.assertIn("strategy_operations", ids)

    def test_get_role_profile_alias(self) -> None:
        p = get_role_profile("Strategy & Operations")
        self.assertEqual(p.id, "strategy_operations")


class TestGapEngine(unittest.TestCase):
    def test_weak_required_triggers_resume_change(self) -> None:
        resume = {
            "sections": {
                "summary": ["Published an internal survey on feature satisfaction."],
                "experience": [
                    {
                        "company": "Acme",
                        "title": "Product Analyst",
                        "bullets": [
                            "Led SQL-driven cohort analysis and A/B tests on funnel dashboards with Amplitude exports.",
                            "Wrote PRDs and discovery briefs with problem statements for checkout drop-off.",
                        ],
                    }
                ],
                "skills": ["SQL", "Amplitude"],
                "projects": [],
            }
        }
        report = analyze_resume_gap_report(resume, "product_analyst")
        self.assertFalse(report["gaps"]["missing_signals"])
        weak = report["gaps"]["weak_matches"]
        self.assertTrue(any(w.get("signal_id") == "user_research_signals" for w in weak))
        self.assertTrue(
            any("Elevate" in line or "elevate" in line for line in report["actions"]["resume_changes"]),
            msg=report["actions"]["resume_changes"][:3],
        )

    def test_missing_project_buildable_adds_project_suggestion(self) -> None:
        resume = {
            "sections": {
                "summary": [],
                "experience": [
                    {
                        "company": "Co",
                        "title": "Analyst",
                        "bullets": ["Facilitated meetings and sponsor check-ins for releases."],
                    }
                ],
                "skills": [],
                "projects": [],
            }
        }
        report = analyze_resume_gap_report(resume, "product_analyst")
        cats = {c["signal_id"]: c["gap_category"] for c in report["gaps"]["classified"]}
        self.assertEqual(cats.get("sql_data"), "project_needed")
        self.assertTrue(
            any("artifact" in s.lower() or "portfolio" in s.lower() for s in report["actions"]["project_suggestions"]),
            msg=report["actions"]["project_suggestions"],
        )

    def test_missing_experience_signal_adds_skill_recommendation(self) -> None:
        resume = {
            "sections": {
                "summary": [],
                "experience": [
                    {
                        "company": "Co",
                        "title": "Analyst",
                        "bullets": ["Ran SQL dashboards and experiments; shipped cohort analyses."],
                    }
                ],
                "skills": ["SQL"],
                "projects": [],
            }
        }
        report = analyze_resume_gap_report(resume, "product_analyst")
        cats = {c["signal_id"]: c["gap_category"] for c in report["gaps"]["classified"]}
        self.assertEqual(cats.get("user_research_signals"), "experience_gap")
        self.assertTrue(
            any("Study" in s or "fundamentals" in s for s in report["actions"]["skill_recommendations"]),
            msg=report["actions"]["skill_recommendations"][:5],
        )

    def test_fit_summary_thin_required_not_solid(self) -> None:
        resume = {
            "sections": {
                "summary": ["Published an internal survey on feature satisfaction."],
                "experience": [
                    {
                        "company": "Acme",
                        "title": "Product Analyst",
                        "bullets": [
                            "Led SQL-driven cohort analysis and A/B tests on funnel dashboards with Amplitude exports.",
                            "Wrote PRDs and discovery briefs with problem statements for checkout drop-off.",
                        ],
                    }
                ],
                "skills": ["SQL", "Amplitude"],
                "projects": [],
            }
        }
        report = analyze_resume_gap_report(resume, "product_analyst")
        self.assertEqual(len(report["gaps"]["missing_signals"]), 0)
        self.assertIn("No required signals are fully missing", report["fit_summary"])
        self.assertNotIn("Overall fit looks solid", report["fit_summary"])

    def test_strategy_operations_has_concrete_actions(self) -> None:
        resume = {
            "sections": {
                "summary": ["Enjoys collaboration."],
                "experience": [
                    {
                        "company": "Globex",
                        "title": "Ops Associate",
                        "bullets": [
                            "Maintained weekly KPI reporting for leadership and joined cross-functional initiatives.",
                        ],
                    }
                ],
                "skills": ["Excel"],
                "projects": [],
            }
        }
        report = analyze_resume_gap_report(resume, "strategy_operations")
        self.assertTrue(report["actions"]["resume_changes"])
        self.assertTrue(
            report["actions"]["project_suggestions"] or report["actions"]["skill_recommendations"],
            msg="Expected at least one portfolio or skill coach line for Strategy & Operations gaps.",
        )

    def test_report_shape(self) -> None:
        resume = {
            "sections": {
                "summary": [],
                "experience": [
                    {
                        "company": "Acme",
                        "title": "BizOps Analyst",
                        "bullets": [
                            "Automated weekly KPI reporting with SQL and Python for GTM leadership.",
                            "Partnered with finance on forecasting and variance analysis.",
                        ],
                    }
                ],
                "skills": ["SQL", "Python"],
                "projects": [],
            }
        }
        report = analyze_resume_gap_report(resume, "bizops")
        self.assertIn("fit_summary", report)
        self.assertIn("strong_matches", report["gaps"])
        self.assertIn("weak_matches", report["gaps"])
        self.assertIn("missing_signals", report["gaps"])
        self.assertIn("classified", report["gaps"])
        self.assertIn("resume_signals", report["gaps"])
        self.assertIn("resume_changes", report["actions"])
        self.assertIn("project_suggestions", report["actions"])
        self.assertIn("skill_recommendations", report["actions"])
        for m in report["gaps"]["classified"]:
            self.assertIn(
                m["gap_category"],
                ("resume_fixable", "project_needed", "experience_gap"),
            )

    def test_actions_include_parallel_stable_ids(self) -> None:
        resume = {
            "sections": {
                "experience": [
                    {
                        "company": "Co",
                        "title": "Analyst",
                        "bullets": ["Ran SQL dashboards and experiments; shipped cohort analyses."],
                    }
                ],
                "skills": ["SQL"],
                "projects": [],
            }
        }
        report = analyze_resume_gap_report(resume, "product_analyst")
        act = report["actions"]
        for key_items, key_lines in (
            ("resume_change_items", "resume_changes"),
            ("project_suggestion_items", "project_suggestions"),
            ("skill_recommendation_items", "skill_recommendations"),
        ):
            self.assertIn(key_items, act)
            items = act[key_items]
            lines = act[key_lines]
            self.assertEqual(len(items), len(lines), msg=(key_items, key_lines))
            for i, row in enumerate(items):
                self.assertEqual(row["text"], lines[i])
                self.assertIsInstance(row["id"], str)
                self.assertTrue(row["id"].startswith("refinery_action_"))

    def test_does_not_invent_employer_in_output(self) -> None:
        resume = {
            "sections": {
                "experience": [
                    {
                        "company": "Contoso",
                        "title": "Intern",
                        "bullets": ["Filed paperwork."],
                    }
                ],
                "skills": [],
            }
        }
        report = analyze_resume_gap_report(resume, "product_analyst")
        blob = str(report).lower()
        for invented in ("palantir", "stripe", "waymo"):
            self.assertNotIn(invented, blob)


if __name__ == "__main__":
    unittest.main()
