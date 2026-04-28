"""Unit tests for experience bullet signal-based ordering."""

import unittest

from app.services.experience_bullet_prioritization import (
    prioritize_experience_bullets,
    prioritize_experience_entry_bullets,
)


class TestExperienceBulletPrioritization(unittest.TestCase):
    def test_gainwell_senior_bsa_strong_bullets_float_to_top(self):
        company = "Gainwell Technologies"
        role = "Senior Business Systems Analyst | UAT Lead"
        bullets = [
            "Supported daily standups and assisted with documentation for the Provider Portal.",
            "Worked on test cases in Jira and Excel for various workstreams.",
            "Resolved 50+ overdue SLA deliverables by reprioritizing backlog and aligning stakeholders.",
            "Stabilized an at-risk Provider Portal initiative by clarifying scope with cross-functional teams.",
            "Assumed functional ownership without documentation and reverse engineered legacy workflows.",
        ]
        out, _ = prioritize_experience_entry_bullets(company, role, bullets)
        self.assertEqual(out[0], bullets[2])
        self.assertIn(out[1], (bullets[3], bullets[4]))
        self.assertIn(out[2], (bullets[3], bullets[4]))
        self.assertIn(out[-1], (bullets[0], bullets[1]))
        self.assertIn(out[-2], (bullets[0], bullets[1]))

    def test_single_bullet_unchanged(self):
        b = ["Only bullet."]
        out, dbg = prioritize_experience_bullets(b, company="X", role="Analyst")
        self.assertEqual(out, b)
        self.assertIsNone(dbg)

    def test_stable_order_on_identical_scores(self):
        bullets = [
            "A task one.",
            "B task two.",
        ]
        out, _ = prioritize_experience_bullets(bullets, company="Co", role="Intern")
        self.assertEqual(out, bullets)


if __name__ == "__main__":
    unittest.main()
