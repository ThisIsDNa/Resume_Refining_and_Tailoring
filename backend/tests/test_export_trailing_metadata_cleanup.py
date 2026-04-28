"""Dict-level trailing location/date cleanup before STEP 3 export validation."""

from __future__ import annotations

import unittest

from app.services.export_docx import _clean_experience_trailing_metadata


class TestCleanExperienceTrailingMetadata(unittest.TestCase):
    def test_location_then_date_removed_and_assigned(self) -> None:
        blocks = [
            {
                "company": "RWS Moravia (Client: Apple)",
                "title": "Business Data Technician",
                "date_range": "",
                "location": "",
                "bullets": [
                    "Increased mapping data accuracy through structured validation.",
                    "Reduced processing time by improving workflow efficiency.",
                    "Maintained strong production adherence in a deadline-driven environment.",
                    "Sunnyvale, CA",
                    "June 2019 - June 2020",
                ],
            }
        ]
        out = _clean_experience_trailing_metadata(blocks)
        self.assertEqual(len(out), 1)
        b = out[0]
        self.assertEqual(len(b["bullets"]), 3)
        self.assertIn("Sunnyvale", b["location"])
        self.assertIn("June", b["date_range"])
        self.assertNotIn("Sunnyvale", " ".join(b["bullets"]))

    def test_date_then_location_order(self) -> None:
        blocks = [
            {
                "company": "Acme",
                "title": "Engineer",
                "date_range": "",
                "location": "",
                "bullets": [
                    "Built the system.",
                    "June 2019 – June 2020",
                    "San Mateo, CA",
                ],
            }
        ]
        out = _clean_experience_trailing_metadata(blocks)
        b = out[0]
        self.assertEqual(b["bullets"], ["Built the system."])
        self.assertIn("San Mateo", b["location"])
        self.assertIn("June", b["date_range"])

    def test_does_not_overwrite_existing_metadata(self) -> None:
        blocks = [
            {
                "company": "Co",
                "title": "Role",
                "date_range": "Jan 2020 - Present",
                "location": "Remote",
                "bullets": ["Did work.", "Sunnyvale, CA", "June 2019 - June 2020"],
            }
        ]
        out = _clean_experience_trailing_metadata(blocks)
        b = out[0]
        self.assertEqual(b["location"], "Remote")
        self.assertEqual(b["date_range"], "Jan 2020 - Present")
        self.assertEqual(b["bullets"], ["Did work."])

    def test_single_trailing_date_only(self) -> None:
        blocks = [
            {
                "company": "Co",
                "title": "Role",
                "date_range": "",
                "location": "",
                "bullets": ["Bullet one.", "June 2019 - June 2020"],
            }
        ]
        out = _clean_experience_trailing_metadata(blocks)
        b = out[0]
        self.assertEqual(b["bullets"], ["Bullet one."])
        self.assertIn("June", b["date_range"])

    def test_no_match_leaves_bullets(self) -> None:
        blocks = [
            {
                "company": "Co",
                "title": "Role",
                "bullets": ["Real achievement with metrics.", "Another solid bullet."],
            }
        ]
        out = _clean_experience_trailing_metadata(blocks)
        self.assertEqual(len(out[0]["bullets"]), 2)


if __name__ == "__main__":
    unittest.main()
