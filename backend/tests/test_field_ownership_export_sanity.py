"""
Targeted sanity: summary strength, experience header ownership, distinct employers/roles,
education/cert/skills sections, and no cross-section leakage (DOCX export path).
"""

from __future__ import annotations

import re
import unittest
from io import BytesIO

from docx import Document

from app.services.export_docx import (
    _build_grounding_corpus,
    build_export_docx_package,
    derive_match_strength,
    strongest_summary_from_resume,
)
from app.services.resume_document_assembly import (
    experience_blocks_to_entries,
    experience_entry_header_lines,
)

import test_docx_experience_render_order as _docx_exp_order


def _docx_paragraphs(docx_bytes: bytes) -> list[str]:
    doc = Document(BytesIO(docx_bytes))
    return [p.text.strip() for p in doc.paragraphs if p.text.strip()]


def _docx_major_section_heading_order(lines: list[str]) -> list[str]:
    """First-seen order of canonical export section headings (deterministic body contract)."""
    keys = frozenset(
        {"SUMMARY", "EXPERIENCE", "PROJECTS", "EDUCATION", "CERTIFICATIONS", "SKILLS"}
    )
    return [ln.strip().upper() for ln in lines if ln.strip().upper() in keys]


# Weak generic outcome the pipeline must not prefer when identity_structured is available.
_WEAK_GENERIC_BSA_CROSSFUNCTIONAL_BA = re.compile(
    r"(?i)business\s+systems?\s+analyst\s+with\s+experience\s+in\s+cross-functional\s+and\s+business\s+analysis",
)


def _section_slice(lines: list[str], start: str, stop: str | None) -> list[str]:
    """Inclusive after start heading; exclusive before stop heading (if any)."""
    u = [x.upper() for x in lines]
    try:
        i0 = u.index(start.upper())
    except ValueError:
        return []
    i1 = len(lines)
    if stop:
        try:
            i1 = u.index(stop.upper())
        except ValueError:
            i1 = len(lines)
    return lines[i0 + 1 : i1]


class TestFieldOwnershipExportSanity(unittest.TestCase):
    _REQ = (
        "Lead cross-functional teams to deliver enterprise software solutions "
        "with regulatory compliance and documented validation."
    )

    def _fixture_resume_data(self) -> dict:
        # Corpus must cover experience bullets (STEP 3 novel-word grounding) and summary tokens.
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

    def _score_mapping_signals(self) -> tuple[dict, dict, dict]:
        job_signals = {"validated_requirements": [self._REQ]}
        mapping_result = {
            "requirement_matches": [
                {
                    "requirement_text": self._REQ,
                    "classification": "strong",
                    "priority": "nice_to_have",
                    "matched_evidence": [{"id": "e1"}],
                }
            ]
        }
        score_result = {"overall_score": 65, "summary": {"matched_requirements": 4}}
        return score_result, mapping_result, job_signals

    def test_experience_entries_company_role_date_then_bullets(self) -> None:
        """Checks 2–4: header order and distinct Gainwell / Tesla / RWS identities."""
        resume = self._fixture_resume_data()
        rows = experience_blocks_to_entries(list(resume["sections"]["experience"]))
        self.assertEqual(len(rows), 3, msg=[(e.company, e.role) for e in rows])
        companies = [(e.company or "").strip() for e in rows]
        roles = [(e.role or "").strip() for e in rows]
        self.assertTrue(all("Gainwell" in companies[0] for _ in [0]))
        self.assertIn("Tesla", companies[1])
        self.assertTrue(any("RWS" in c for c in companies))
        self.assertIn("Senior Business Systems Analyst", roles[0])
        self.assertIn("UAT Lead", roles[0])
        self.assertIn("Autopilot", roles[1])
        self.assertIn("Business Data Technician", roles[2])
        for ent in rows:
            lines = experience_entry_header_lines(ent)
            self.assertGreaterEqual(len(lines), 3, msg=lines)
            self.assertTrue((ent.company or "").strip(), msg="company visible")
            self.assertTrue((ent.role or "").strip(), msg="role visible")
            self.assertTrue(lines[0] == (ent.company or "").strip())
            self.assertTrue(lines[1] == (ent.role or "").strip())
            joined_meta = " ".join(lines[2:])
            self.assertRegex(
                joined_meta,
                r"(19|20)\d{2}|Present|Current",
                msg=lines,
            )

    def test_end_to_end_export_field_ownership_and_sections(self) -> None:
        """Checks 1, 5–8 via full DOCX export; 2–4 reinforced on rendered body text."""
        resume = self._fixture_resume_data()
        score_result, mapping_result, job_signals = self._score_mapping_signals()
        ms = derive_match_strength(score_result, mapping_result, job_signals)
        self.assertEqual(ms, "strong")

        grounding = _build_grounding_corpus(
            resume, resume["sections"]["experience"], []
        )
        summary, summary_source = strongest_summary_from_resume(
            "", ms, resume, grounding
        )
        # Check 1: prefer dense identity-forward summary when corpus gates pass; else structured.
        self.assertIn(
            summary_source,
            ("identity_forward_dense", "identity_structured"),
            msg=f"unexpected summary_source={summary_source}: {summary!r}",
        )
        self.assertIsNone(
            _WEAK_GENERIC_BSA_CROSSFUNCTIONAL_BA.search(summary),
            msg=f"weak generic BSA/cross-functional/BA outcome must not win: {summary!r}",
        )
        low = summary.lower()
        if "operational efficiency" in low and "business requirements" in low:
            self.fail(f"weak generic outcome summary leaked through: {summary!r}")

        rewrite_result: dict = {"bullet_changes": [], "tailored_summary": ""}
        docx_bytes, _fn, err, ok = build_export_docx_package(
            resume, rewrite_result, score_result, mapping_result, job_signals
        )
        self.assertFalse(err, msg=err)
        self.assertEqual(ok, "DOCX EXPORT VALIDATED - READY")

        lines = _docx_paragraphs(docx_bytes)
        joined = "\n".join(lines)

        # Check 5–6: dedicated sections and sane content (no skill buckets in EDUCATION).
        edu_block = "\n".join(_section_slice(lines, "EDUCATION", "CERTIFICATIONS")).lower()
        self.assertIn("computer science", edu_block)
        self.assertIn("mba", edu_block)
        self.assertNotIn("testing & governance", edu_block)
        self.assertNotIn("documentation & modeling", edu_block)
        self.assertNotIn(
            "certified business analysis professional",
            edu_block,
            msg="certification titles must not appear under EDUCATION",
        )

        cert_block = "\n".join(_section_slice(lines, "CERTIFICATIONS", "SKILLS")).lower()
        self.assertIn("iiba", cert_block)
        self.assertIn("pmi", cert_block)
        self.assertNotIn(
            "computer science",
            cert_block,
            msg="degree language must not appear under CERTIFICATIONS",
        )

        skills_block = "\n".join(_section_slice(lines, "SKILLS", None)).lower()
        # Check 7: all grouped categories survive export.
        for label in (
            "systems & platforms",
            "data & analytics",
            "testing & governance",
            "documentation & modeling",
        ):
            with self.subTest(category=label):
                self.assertIn(label, skills_block)

        # Check 8: no leaked bucket lines under PROJECTS or inside EXPERIENCE body.
        exp_body = "\n".join(_section_slice(lines, "EXPERIENCE", "PROJECTS")).lower()
        self.assertNotRegex(exp_body, r"education\s*:")
        self.assertNotRegex(exp_body, r"certifications\s*:")
        self.assertNotIn("documentation & modeling:", exp_body)
        self.assertNotIn("testing & governance:", exp_body)

        proj_body = "\n".join(_section_slice(lines, "PROJECTS", "EDUCATION")).lower()
        self.assertNotRegex(proj_body, r"education\s*:")
        self.assertNotRegex(proj_body, r"certifications\s*:")
        self.assertNotIn("documentation & modeling:", proj_body)
        self.assertIn("react", proj_body)

        # Check 8: deterministic major section order in rendered body.
        self.assertEqual(
            _docx_major_section_heading_order(lines),
            [
                "SUMMARY",
                "EXPERIENCE",
                "PROJECTS",
                "EDUCATION",
                "CERTIFICATIONS",
                "SKILLS",
            ],
            msg=_docx_major_section_heading_order(lines),
        )

        # Check 2 (DOCX): each experience entry — company, role, date-bearing line, then bullets.
        exp_meta = _docx_exp_order._experience_section_meta(docx_bytes)
        segments = _docx_exp_order._split_experience_entries(exp_meta)
        self.assertEqual(len(segments), 3, msg=[(t, s) for t, s in exp_meta[:12]])
        lb = _docx_exp_order._LIST_BULLET
        for i, (want_co, want_role) in enumerate(
            (
                ("Gainwell", "Senior Business Systems Analyst"),
                ("Tesla", "Data Specialist"),
                ("RWS", "Business Data Technician"),
            )
        ):
            seg = segments[i]
            id_lines = [(t, st) for t, st in seg if st != lb]
            self.assertGreaterEqual(
                len(id_lines),
                4,
                msg=f"entry {i}: expected ≥4 identity lines before bullets, got {id_lines!r}",
            )
            self.assertIn(want_co, id_lines[0][0], msg=id_lines[0])
            self.assertIn(want_role, id_lines[1][0], msg=id_lines[1])
            joined_hdr = " ".join(t for t, _st in id_lines[2:])
            self.assertRegex(
                joined_hdr,
                r"(19|20)\d{2}|Present|Current",
                msg=f"entry {i} location+date lines: {id_lines[2:]!r}",
            )

        # Visible anchors for recruiters (body, not only structured model).
        self.assertRegex(joined, r"(?i)gainwell\s+technologies")
        self.assertIn("Tesla", joined)
        self.assertRegex(joined, r"(?i)rws\s+moravia")
        self.assertIn("Senior Business Systems Analyst", joined)
        self.assertIn("Data Specialist", joined)
        self.assertIn("Business Data Technician", joined)


if __name__ == "__main__":
    unittest.main()
