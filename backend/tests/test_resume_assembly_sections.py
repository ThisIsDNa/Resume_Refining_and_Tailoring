"""Structural assembly: experience identity, skills groups, project isolation."""

import unittest

from app.services.export_docx import _extract_contact_lines
from app.services.resume_document_assembly import (
    ExperienceEntry,
    _finalize_experience_entries_sealed,
    _parse_role_header_line,
    _split_oversized_bullets,
    build_resume_document_payload,
    dict_rows_to_certification_entries,
    normalize_experience_entry_identity,
    prepare_experience_blocks_for_docx,
    prepare_project_blocks_for_docx,
    skill_bucket_line_redirects_to_skills,
    skills_to_display_lines,
    strip_skill_bucket_lines_from_experience_dict_blocks,
)


class TestResumeAssemblySections(unittest.TestCase):
    def test_company_first_pipe_line_maps_role_and_company(self):
        r, c, d, loc, _ov = _parse_role_header_line(
            "Gainwell Technologies | Senior Business Systems Analyst | 2024 - Present | Remote"
        )
        self.assertEqual(c, "Gainwell Technologies")
        self.assertIn("Senior Business", r)
        self.assertIn("2024", d)
        self.assertIn("Remote", loc)

    def test_prepare_experience_promotes_three_line_company_role_dateline(self) -> None:
        """Company / role / (location | date) lines merge into one header before bullets."""
        blocks = [
            {
                "company": "",
                "title": "",
                "bullets": [
                    "Tesla",
                    "Data Specialist (Autopilot)",
                    "San Mateo, CA | July 2020 – June 2022",
                    "Built dashboards for leadership.",
                ],
            }
        ]
        out = prepare_experience_blocks_for_docx(blocks)
        self.assertEqual(len(out), 1)
        merged = out[0]["bullets"][0]
        self.assertIn("Tesla", merged)
        self.assertIn("Data Specialist", merged)
        self.assertIn("2020", merged)
        self.assertEqual(out[0]["bullets"][1], "Built dashboards for leadership.")

    def test_prepare_experience_promotes_date_before_location_pipe(self) -> None:
        blocks = [
            {
                "company": "",
                "title": "",
                "bullets": [
                    "Acme Corp",
                    "Senior Analyst",
                    "April 2024 – Present | Remote",
                    "Delivered reporting pack.",
                ],
            }
        ]
        out = prepare_experience_blocks_for_docx(blocks)
        merged = out[0]["bullets"][0]
        self.assertIn("Acme", merged)
        self.assertIn("Analyst", merged)
        self.assertIn("2024", merged)

    def test_remote_is_not_company_after_normalize(self):
        e = normalize_experience_entry_identity(
            ExperienceEntry(
                company="Remote",
                role="Senior Business Systems Analyst",
                date="April 2024 – Present",
                location="",
                bullets=[],
            )
        )
        self.assertEqual(e.company, "")
        self.assertIn("Senior", e.role)
        self.assertIn("Remote", e.location)

    def test_skills_preserves_multiple_category_lines(self):
        lines = skills_to_display_lines(
            [
                "Data & Analytics: SQL, Power BI",
                "Systems & Platforms: X, Y",
                "Testing & Governance: SLA, QA",
            ]
        )
        self.assertEqual(len(lines), 3)
        self.assertIn("Testing & Governance", lines[2])

    def test_project_strip_moves_skill_bucket_to_extra(self):
        blocks, extra, _, _ = prepare_project_blocks_for_docx(
            [
                {
                    "name": "Sample Project",
                    "bullets": [
                        "Shipped feature A.",
                        "Testing & Governance: SLA Management, QA Framework Design",
                    ],
                }
            ]
        )
        self.assertEqual(blocks[0]["bullets"], ["Shipped feature A."])
        self.assertTrue(extra[0].startswith("Testing & Governance"))

    def test_extract_linkedin_plain_path_without_https(self) -> None:
        raw = "Dustin Na\nlinkedin.com/in/dustin-na\n"
        _n, _e, _p, li, _g = _extract_contact_lines(raw, None)
        self.assertEqual(li, "linkedin.com/in/dustin-na")

    def test_split_frequently_placed_ambiguity_bullet(self) -> None:
        one = (
            "Frequently placed into ambiguous, undocumented environments "
            "requiring rapid discovery."
        )
        out = _split_oversized_bullets([one, "Other bullet."])
        self.assertEqual(len(out), 3, msg=out)
        self.assertTrue(out[0].lower().startswith("frequently placed"))
        self.assertTrue(out[1].lower().startswith("requiring"))
        self.assertEqual(out[2], "Other bullet.")

    def test_split_frequently_placed_ambiguity_bullet_comma_splice(self) -> None:
        combined = (
            "Frequently placed into ambiguous, undocumented environments requiring rapid discovery, "
            "Lead end-to-end functional validation aligning business rules with technical delivery."
        )
        out = _split_oversized_bullets([combined])
        self.assertEqual(len(out), 2, msg=out)
        self.assertTrue(out[0].lower().startswith("frequently placed"))
        self.assertTrue(out[1].lower().startswith("lead end-to-end"))

    def test_split_frequently_placed_merges_with_validation_followup_bullet(self) -> None:
        amb = (
            "Frequently placed into ambiguous, undocumented environments requiring rapid discovery."
        )
        val = "Lead end-to-end functional validation aligning business rules with technical delivery."
        out = _split_oversized_bullets([amb, val, "Other bullet."])
        self.assertEqual(len(out), 3, msg=out)
        self.assertTrue(out[0].lower().startswith("frequently placed"))
        self.assertTrue(out[1].lower().startswith("lead end-to-end"))
        self.assertEqual(out[2], "Other bullet.")

    def test_certifications_drop_collaboration_skill_colon_row(self) -> None:
        rows = dict_rows_to_certification_entries(
            [
                {"name": "PMI-ACP", "issuer": "PMI", "date": "2021", "bullets": []},
                {
                    "name": "Collaboration: cross-functional workshops and stakeholder alignment",
                    "issuer": "",
                    "date": "",
                    "bullets": [],
                },
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("PMI-ACP", rows[0].name)

    def test_skills_display_strips_core_skills_label(self) -> None:
        lines = skills_to_display_lines(
            ["Data & Analytics: SQL", "Core Skills", "Systems & Platforms: X"]
        )
        self.assertNotIn("Core Skills", lines)

    def test_project_drop_section_leak_lines(self) -> None:
        scrubbed, _extra_s, _e, _c = prepare_project_blocks_for_docx(
            [
                {
                    "name": "Personal Project",
                    "bullets": [
                        "Built a dashboard.",
                        "Education",
                        "Certifications",
                        "Core Skills",
                    ],
                }
            ]
        )
        self.assertEqual(scrubbed[0]["bullets"], ["Built a dashboard."])

    def test_project_drops_itil_cert_style_line(self) -> None:
        scrubbed, _s, _e, _c = prepare_project_blocks_for_docx(
            [
                {
                    "name": "Personal Project",
                    "bullets": [
                        "Shipped dashboard.",
                        "ITIL 4 Foundation — issued 2022",
                    ],
                }
            ]
        )
        self.assertEqual(scrubbed[0]["bullets"], ["Shipped dashboard."])

    def test_project_routes_academic_credentials_colon_to_education(self) -> None:
        scrubbed, _extra_s, extra_edu, _c = prepare_project_blocks_for_docx(
            [
                {
                    "name": "Personal Project",
                    "bullets": [
                        "Shipped analytics UI.",
                        "Academic credentials: MBA, Metro College",
                    ],
                }
            ]
        )
        self.assertEqual(scrubbed[0]["bullets"], ["Shipped analytics UI."])
        self.assertTrue(any("mba" in (e.get("degree") or "").lower() for e in extra_edu))

    def test_skill_bucket_detector_matches_grouped_category_lines(self) -> None:
        samples = [
            "Testing & Governance: SLA Management, QA Framework Design, Defect Triage",
            "Systems & Platforms: Dynamics 365 CRM, Essette, GIA, ServiceNow",
            "Documentation & Modeling: Process Mapping, Workflow Design, Requirement Decomposition",
            "Data & Analytics: SQL, Power BI, Tableau, Excel, Python",
        ]
        for s in samples:
            self.assertTrue(
                skill_bucket_line_redirects_to_skills(s),
                msg=f"expected skill bucket redirect: {s!r}",
            )
        self.assertFalse(skill_bucket_line_redirects_to_skills("Shipped a feature end-to-end."))

    def test_experience_skill_buckets_redirect_to_skills_payload(self) -> None:
        skill_lines = [
            "Testing & Governance: SLA Management, QA Framework Design, Defect Triage",
            "Systems & Platforms: Dynamics 365 CRM, Essette, GIA, ServiceNow",
            "Documentation & Modeling: Process Mapping, Workflow Design, Requirement Decomposition",
            "Data & Analytics: SQL, Power BI, Tableau, Excel, Python",
        ]
        scrubbed, redirected = strip_skill_bucket_lines_from_experience_dict_blocks(
            [
                {
                    "company": "Acme Corp",
                    "title": "Business Analyst",
                    "date_range": "2020 – Present",
                    "bullets": ["Owned requirements workshops.", *skill_lines],
                }
            ]
        )
        self.assertEqual(scrubbed[0]["bullets"], ["Owned requirements workshops."])
        self.assertEqual(redirected, skill_lines)

        payload = build_resume_document_payload(
            name="T",
            contact="t@example.com",
            summary="Summary.",
            summary_source="test",
            experience_blocks=[
                {
                    "company": "Acme Corp",
                    "title": "Business Analyst",
                    "date_range": "2020 – Present",
                    "bullets": ["Owned requirements workshops.", *skill_lines],
                }
            ],
            projects=[],
            education=[],
            certifications=[],
            skills=["Agile"],
        )
        for line in skill_lines:
            self.assertIn(line, payload.skills)
        for ent in payload.experience:
            for b in ent.bullets:
                self.assertFalse(
                    skill_bucket_line_redirects_to_skills(b),
                    msg=f"skill bucket must not remain in experience bullets: {b!r}",
                )

    def test_finalize_peels_trailing_location_then_date_into_metadata(self) -> None:
        """RWS-style city/state + month span leaked after real bullets → header fields, not bullets."""
        anchor = ExperienceEntry(
            "Gainwell Technologies",
            "Senior Analyst",
            "2020 - Present",
            "Remote",
            ["Delivered outcomes."],
        )
        rws = ExperienceEntry(
            "RWS Moravia (Client: Apple)",
            "Business Data Technician",
            "",
            "",
            [
                "Increased mapping data accuracy through structured validation and error correction processes.",
                "Reduced processing time by improving workflow efficiency and data handling procedures.",
                "Maintained strong production adherence in a deadline-driven environment.",
                "Sunnyvale, CA",
                "June 2019 - June 2020",
            ],
        )
        sealed = _finalize_experience_entries_sealed([anchor, rws])
        self.assertEqual(len(sealed), 2)
        row = sealed[1]
        self.assertIn("Sunnyvale", row.location)
        self.assertIn("2019", row.date)
        self.assertIn("2020", row.date)
        self.assertEqual(len(row.bullets), 3)
        joined = " ".join(row.bullets)
        self.assertNotIn("Sunnyvale", joined)
        self.assertNotIn("June 2019", joined)

    def test_finalize_peels_trailing_date_then_location_into_metadata(self) -> None:
        month_span = "June 2019 – June 2020"
        e = ExperienceEntry(
            "Acme Corp",
            "Engineer",
            "",
            "",
            [
                "Built the system.",
                month_span,
                "Sunnyvale, CA",
            ],
        )
        sealed = _finalize_experience_entries_sealed([e])
        self.assertEqual(len(sealed), 1)
        row = sealed[0]
        self.assertIn("Sunnyvale", row.location)
        self.assertIn("June", row.date)
        self.assertEqual(row.bullets, ["Built the system."])


if __name__ == "__main__":
    unittest.main()
