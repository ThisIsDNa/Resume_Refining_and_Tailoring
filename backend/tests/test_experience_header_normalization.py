"""Leading location/date lines promoted from first two bullets into header fields."""

from __future__ import annotations

import unittest

from app.services.experience_header_normalization import (
    _normalize_experience_headers,
    apply_experience_header_normalization_to_resume_data,
)


class TestNormalizeExperienceHeaders(unittest.TestCase):
    def test_location_then_date_at_bullet_prefix(self) -> None:
        blocks = [
            {
                "company": "RWS Moravia (Client: Apple)",
                "title": "Business Data Technician",
                "date_range": "",
                "location": "",
                "bullets": [
                    "Sunnyvale, CA",
                    "June 2019 - June 2020",
                    "Increased mapping data accuracy.",
                ],
            }
        ]
        out = _normalize_experience_headers(blocks)
        b = out[0]
        self.assertIn("Sunnyvale", b["location"])
        self.assertIn("June", b["date_range"])
        self.assertEqual(b["bullets"], ["Increased mapping data accuracy."])

    def test_date_then_location_at_bullet_prefix(self) -> None:
        blocks = [
            {
                "company": "Acme",
                "title": "Engineer",
                "date_range": "",
                "location": "",
                "bullets": [
                    "June 2019 – June 2020",
                    "San Mateo, CA",
                    "Built the system.",
                ],
            }
        ]
        out = _normalize_experience_headers(blocks)
        b = out[0]
        self.assertIn("San Mateo", b["location"])
        self.assertIn("June", b["date_range"])
        self.assertEqual(b["bullets"], ["Built the system."])

    def test_skips_when_metadata_already_set(self) -> None:
        blocks = [
            {
                "company": "Co",
                "title": "Role",
                "date_range": "2020 - Present",
                "location": "Remote",
                "bullets": ["Sunnyvale, CA", "June 2019 - June 2020", "Did work."],
            }
        ]
        out = _normalize_experience_headers(blocks)
        self.assertEqual(
            out[0]["bullets"],
            ["Sunnyvale, CA", "June 2019 - June 2020", "Did work."],
        )

    def test_skips_when_first_bullets_not_pure_pair(self) -> None:
        blocks = [
            {
                "company": "Co",
                "title": "Role",
                "date_range": "",
                "location": "",
                "bullets": [
                    "Led cross-functional initiatives.",
                    "Sunnyvale, CA",
                    "June 2019 - June 2020",
                ],
            }
        ]
        out = _normalize_experience_headers(blocks)
        self.assertEqual(len(out[0]["bullets"]), 3)

    def test_apply_in_place_to_resume_data(self) -> None:
        resume = {
            "sections": {
                "experience": [
                    {
                        "company": "X",
                        "title": "Y",
                        "date_range": "",
                        "location": "",
                        "bullets": ["Austin, TX", "January 2020 - Present", "Shipped features."],
                    }
                ]
            }
        }
        apply_experience_header_normalization_to_resume_data(resume)
        b = resume["sections"]["experience"][0]
        self.assertIn("Austin", b["location"])
        self.assertEqual(b["bullets"], ["Shipped features."])


if __name__ == "__main__":
    unittest.main()
