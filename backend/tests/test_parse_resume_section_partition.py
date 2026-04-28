"""Section-aware tail partitioning (parse_resume) + experience segmentation defense."""

from __future__ import annotations

import unittest

from app.services.parse_resume import (
    experience_lines_for_identity_segmentation,
    normalize_resume_structure,
    partition_tail_lines_by_resume_sections,
)
from app.services.resume_document_assembly import build_experience_entries_identity_first


class TestPartitionTailLinesByResumeSections(unittest.TestCase):
    def test_legacy_passthrough_without_experience_heading(self) -> None:
        lines = [
            "Gainwell Technologies | Senior Business Systems Analyst | April 2024 – Present | Remote",
            "Led UAT.",
            "PROJECTS",
            "Portfolio App — Python",
        ]
        exp, proj, edu, cert, sk, sx = partition_tail_lines_by_resume_sections(lines)
        self.assertEqual(exp, lines)
        self.assertEqual(proj, [])
        self.assertEqual(edu, [])
        self.assertEqual(cert, [])
        self.assertEqual(sk, [])
        self.assertEqual(sx, [])

    def test_explicit_experience_heading_excludes_later_sections(self) -> None:
        lines = [
            "EXPERIENCE",
            "Gainwell Technologies | Senior Business Systems Analyst | April 2024 – Present | Remote",
            "Led UAT for Provider Portal.",
            "Tesla | Data Specialist (Autopilot) | July 2020 – June 2022 | San Mateo, CA",
            "Supported Autopilot data pipelines.",
            "RWS Moravia (Client: Apple) | Business Data Technician | June 2019 – June 2020 | Sunnyvale, CA",
            "Maintained localization data workflows.",
            "PROJECTS",
            "Portfolio Analytics Dashboard | Python | 2024",
            "Built KPI reporting views.",
            "CERTIFICATIONS",
            "ITIL Foundation | PeopleCert | 2021",
        ]
        exp, proj, edu, cert, sk, sx = partition_tail_lines_by_resume_sections(lines)
        self.assertEqual(len(exp), 6)
        self.assertIn("Gainwell", exp[0])
        self.assertEqual(len(proj), 2)
        self.assertEqual(proj[0], "Portfolio Analytics Dashboard | Python | 2024")
        self.assertEqual(len(cert), 1)
        self.assertEqual(cert[0], "ITIL Foundation | PeopleCert | 2021")
        self.assertEqual(edu, [])
        self.assertEqual(sk, [])
        self.assertEqual(sx, [])

    def test_experience_lines_for_segmentation_matches_partition(self) -> None:
        lines = [
            "EXPERIENCE",
            "Gainwell Technologies | Analyst | Jan 2020 – Dec 2020 | Remote",
            "Did work.",
            "SKILLS",
            "SQL, Python",
        ]
        exp, _, _, _, skill_lines, _ = partition_tail_lines_by_resume_sections(lines)
        self.assertEqual(experience_lines_for_identity_segmentation(lines), exp)
        self.assertEqual(skill_lines, ["SQL, Python"])


class TestNormalizeResumeStructureSections(unittest.TestCase):
    def test_normalize_splits_projects_when_experience_heading_present(self) -> None:
        parsed = {
            "source_filename": "t.docx",
            "parse_ok": True,
            "body_text": "",
            "raw_paragraphs": [
                "Name Person",
                "EXPERIENCE",
                "Acme Corp | Engineer | 2020 – 2021 | Remote",
                "Shipped features.",
                "PROJECTS",
                "My Portfolio App",
                "Demo bullet for project.",
            ],
        }
        out = normalize_resume_structure(parsed)
        sec = out["sections"]
        self.assertEqual(len(sec["experience"][0]["bullets"]), 2)
        self.assertIn("Acme", sec["experience"][0]["bullets"][0])
        self.assertEqual(len(sec["projects"]), 1)
        self.assertEqual(sec["projects"][0]["name"], "My Portfolio App")
        self.assertEqual(sec["projects"][0]["bullets"], ["Demo bullet for project."])


class TestMonolithicBlockWithSectionHeadings(unittest.TestCase):
    def test_identity_first_yields_three_employers_no_ghost_rows(self) -> None:
        blocks = [
            {
                "company": "",
                "title": "",
                "date_range": "",
                "location": "",
                "bullets": [
                    "EXPERIENCE",
                    "Gainwell Technologies | Senior Business Systems Analyst | April 2024 – Present | Remote",
                    "Led UAT for Provider Portal.",
                    "Tesla | Data Specialist (Autopilot) | July 2020 – June 2022 | San Mateo, CA",
                    "Supported Autopilot data pipelines.",
                    "RWS Moravia (Client: Apple) | Business Data Technician | June 2019 – June 2020 | Sunnyvale, CA",
                    "Maintained localization data workflows.",
                    "PROJECTS",
                    "Portfolio Analytics Dashboard | Python | 2024",
                    "Built KPI reporting views.",
                    "CERTIFICATIONS",
                    "ITIL Foundation | PeopleCert | 2021",
                ],
            }
        ]
        rows = build_experience_entries_identity_first(blocks)
        self.assertEqual(len(rows), 3)
        companies = [(r.company or "").strip() for r in rows]
        self.assertTrue(all(c for c in companies))
        self.assertTrue(any("Gainwell" in c for c in companies))
        self.assertTrue(any("Tesla" in c for c in companies))
        self.assertTrue(any("RWS" in c for c in companies))
        self.assertFalse(any("Portfolio" in c for c in companies))
        self.assertFalse(any("ITIL" in c for c in companies))


if __name__ == "__main__":
    unittest.main()
