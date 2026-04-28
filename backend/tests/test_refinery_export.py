"""Refinery transform + export package (gap-guided, no Tailor JD rewrite)."""

from __future__ import annotations

import copy
import unittest

from app.services.export_docx import DOCX_EXPORT_VALIDATION_SUCCESS, build_export_docx_package
from app.services.gap_analysis import analyze_resume_gap_report
from app.services.refinery_transform import (
    apply_refinery_actions,
    build_refinery_export_shims,
)


def _rich_resume_fixture() -> dict:
    """Same shape as field-ownership export sanity (validates end-to-end)."""
    raw_text = "\n".join(
        [
            "Jane Doe",
            "jane@example.com | 555-0100",
            "",
            "Senior Business Systems Analyst Senior UAT Lead Gainwell Tesla RWS Moravia",
            "user acceptance testing regulatory compliance enterprise cross-functional",
            "business analysis stakeholder management data quality project delivery",
            "Led UAT for Provider Portal.",
            "Supported Autopilot data pipelines.",
            "Maintained localization data workflows.",
            "Systems & Platforms: Azure, Jira",
            "Data & Analytics: SQL, Power BI",
            "Testing & Governance: SLA Management, QA",
            "Documentation & Modeling: BRD, process maps",
            "Bachelor of Science in Computer Science from State University",
            "CBAP IIBA certification",
            "PMI-ACP certification program",
        ]
    )
    experience = [
        {
            "company": "Gainwell Technologies",
            "title": "Senior Business Systems Analyst / Senior UAT Lead",
            "date_range": "April 2024 – Present",
            "location": "Remote",
            "bullets": ["Led UAT for Provider Portal."],
        },
        {
            "company": "Tesla",
            "title": "Data Specialist (Autopilot)",
            "date_range": "July 2020 – June 2022",
            "location": "San Mateo, CA",
            "bullets": ["Supported Autopilot data pipelines."],
        },
        {
            "company": "RWS Moravia (Client: Apple)",
            "title": "Business Data Technician",
            "date_range": "June 2019 – June 2020",
            "location": "Sunnyvale, CA",
            "bullets": ["Maintained localization data workflows."],
        },
    ]
    projects = [
        {
            "name": "Personal Project — Analytics Dashboard",
            "subtitle": "",
            "bullets": [
                "Built prototype using React and API integration.",
                "Education: MBA, Metro College",
                "Certifications: PMI-ACP — 2021",
                "Documentation & Modeling: process maps for portfolio",
            ],
        }
    ]
    education = [
        {
            "degree": "B.S. Computer Science",
            "institution": "State University",
            "date": "2014",
            "location": "",
            "bullets": [],
        }
    ]
    certifications = [
        {
            "name": "Certified Business Analysis Professional",
            "issuer": "IIBA",
            "date": "2018",
            "bullets": [],
        }
    ]
    skills = ["Data & Analytics: SQL, Power BI"]
    return {
        "raw_text": raw_text,
        "sections": {
            "experience": experience,
            "projects": projects,
            "education": education,
            "certifications": certifications,
            "skills": skills,
        },
    }


class TestRefineryTransform(unittest.TestCase):
    def test_resume_changes_drive_grounded_bullet_merge(self) -> None:
        resume = {
            "raw_text": "Pat pat@ex.com",
            "sections": {
                "experience": [
                    {
                        "company": "Co",
                        "title": "Analyst",
                        "date_range": "2020 – Present",
                        "location": "",
                        "bullets": ["Facilitated sponsor meetings for quarterly releases."],
                    }
                ],
                "projects": [],
                "skills": ["SQL", "Excel"],
                "summary": [],
            },
        }
        gap = {
            "actions": {
                "resume_changes": [
                    "Surface **SQL / relational data querying** explicitly with outcome language."
                ],
                "project_suggestions": [],
                "skill_recommendations": [],
            },
            "gaps": {"classified": []},
        }
        refined = apply_refinery_actions(copy.deepcopy(resume), gap)
        bullet = refined["sections"]["experience"][0]["bullets"][0]
        self.assertIn("sql", bullet.lower(), msg=bullet)

    def test_no_new_experience_blocks(self) -> None:
        resume = {
            "sections": {
                "experience": [
                    {
                        "company": "A",
                        "title": "T",
                        "bullets": ["Did things with reporting."],
                    }
                ],
                "skills": ["KPI", "metrics"],
                "projects": [],
            }
        }
        gap = {
            "actions": {
                "resume_changes": [
                    "Elevate **Metrics, KPIs, and reporting** on your resume with clearer proof."
                ],
                "project_suggestions": [],
                "skill_recommendations": [],
            },
            "gaps": {"classified": []},
        }
        refined = apply_refinery_actions(copy.deepcopy(resume), gap)
        self.assertEqual(len(refined["sections"]["experience"]), 1)


class TestRefineryExportPackage(unittest.TestCase):
    def test_export_validates_after_refinery_pipeline(self) -> None:
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
        )
        self.assertFalse(err, msg=err)
        self.assertEqual(ok, DOCX_EXPORT_VALIDATION_SUCCESS)
        self.assertTrue(len(docx_bytes) > 2000, msg="expected non-trivial docx bytes")

    def test_transform_preserves_section_shape_on_real_gap_report(self) -> None:
        resume = _rich_resume_fixture()
        before = copy.deepcopy(resume)
        gap = analyze_resume_gap_report(resume, "product_analyst", job_description="")
        refined = apply_refinery_actions(copy.deepcopy(resume), gap)
        self.assertEqual(len(refined["sections"]["experience"]), len(before["sections"]["experience"]))
        self.assertEqual(len(refined["sections"]["projects"]), len(before["sections"]["projects"]))
        for i, block in enumerate(before["sections"]["experience"]):
            self.assertEqual(
                len(refined["sections"]["experience"][i]["bullets"]),
                len(block["bullets"]),
            )
