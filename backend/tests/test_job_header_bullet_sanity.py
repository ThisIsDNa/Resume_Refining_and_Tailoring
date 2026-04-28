"""
Targeted sanity: job-header-shaped lines must not remain in experience bullets.

Run with visible prints:
  python -m pytest tests/test_job_header_bullet_sanity.py -v -s
"""

from __future__ import annotations

import sys
import unittest

from app.services.resume_document_assembly import (
    ExperienceEntry,
    _line_is_embedded_identity_fragment,
    _line_looks_like_role_header,
    build_resume_document_payload,
    experience_blocks_to_entries,
    validate_resume_document_payload,
)


THREE_JOB_BLOCK = {
    "company": "",
    "title": "",
    "date_range": "",
    "location": "",
    "bullets": [
        "Gainwell Technologies | Senior Business Systems Analyst / Senior UAT Lead | April 2024 – Present | Remote",
        "Led UAT for Provider Portal.",
        "Tesla | Data Specialist (Autopilot) | July 2020 – June 2022 | San Mateo, CA",
        "Supported Autopilot data pipelines.",
        "RWS Moravia (Client: Apple) | Business Data Technician | June 2019 – June 2020 | Sunnyvale, CA",
        "Maintained localization data workflows.",
    ],
}

# Full pipe lines that must never appear as bullets after segmentation.
_EXPECTED_IDENTITY_PIPE_PREFIXES = (
    "gainwell technologies | senior business systems analyst",
    "tesla | data specialist",
    "rws moravia (client: apple)",
)


def _print_entries_indexed(entries: list[ExperienceEntry], *, label: str) -> None:
    print(f"\n{'=' * 72}\nJOB_HEADER_BULLET_SANITY: {label}\n{'=' * 72}", file=sys.stderr)
    for i, e in enumerate(entries):
        print(f"\n--- experience[{i}] ---", file=sys.stderr)
        print(f"  company : {e.company!r}", file=sys.stderr)
        print(f"  role    : {e.role!r}", file=sys.stderr)
        print(f"  date    : {e.date!r}", file=sys.stderr)
        print(f"  location: {e.location!r}", file=sys.stderr)
        print(f"  bullets ({len(e.bullets)}):", file=sys.stderr)
        for j, b in enumerate(e.bullets):
            print(f"    [{j}] {b!r}", file=sys.stderr)


class TestJobHeaderBulletSanity(unittest.TestCase):
    def _assert_no_header_bullets(self, entries: list[ExperienceEntry], *, msg: str) -> None:
        for ei, e in enumerate(entries):
            for j, b in enumerate(e.bullets):
                bt = str(b).strip()
                if _line_looks_like_role_header(bt):
                    self.fail(f"{msg}: experience[{ei}].bullets[{j}] matches job-header pattern: {bt!r}")

    def _assert_identity_pipe_lines_not_in_bullets(self, entries: list[ExperienceEntry]) -> None:
        """Gainwell/Tesla/RWS pipe-style identity rows must not survive as bullet text."""
        for ei, e in enumerate(entries):
            for j, b in enumerate(e.bullets):
                low = str(b).strip().lower()
                if "|" not in low:
                    continue
                for prefix in _EXPECTED_IDENTITY_PIPE_PREFIXES:
                    if low.startswith(prefix):
                        self.fail(
                            f"identity pipe line leaked into experience[{ei}].bullets[{j}]: {b!r}"
                        )

    def _assert_entries_begin_with_identities(self, entries: list[ExperienceEntry]) -> None:
        companies = [(x.company or "").lower() for x in entries]
        joined = " ".join(companies)
        self.assertIn("gainwell", joined)
        self.assertIn("tesla", joined)
        self.assertIn("rws", joined)

    def test_three_job_flat_block_print_and_invariants(self) -> None:
        rows = experience_blocks_to_entries([THREE_JOB_BLOCK])
        _print_entries_indexed(rows, label="three_job_flat_block")
        self._assert_no_header_bullets(rows, msg="three_job_flat_block")
        self._assert_identity_pipe_lines_not_in_bullets(rows)
        self._assert_entries_begin_with_identities(rows)
        self.assertEqual(len(rows), 3)
        for b in rows[0].bullets:
            self.assertFalse(
                _line_looks_like_role_header(b),
                msg=f"first entry must be true bullets only: {b!r}",
            )
        payload = build_resume_document_payload(
            name="Test",
            contact="t@example.com",
            summary="Summary for contract check.",
            summary_source="test",
            experience_blocks=[THREE_JOB_BLOCK],
            projects=[],
            education=[],
            certifications=[],
            skills=["Data & Analytics: SQL"],
        )
        validate_resume_document_payload(payload)

    def test_structured_embedded_tesla_print_and_invariants(self) -> None:
        filler = ["Achievement line %s for UAT coverage." % i for i in range(5)]
        tesla = (
            "Tesla | Data Specialist (Autopilot) | July 2020 – June 2022 | San Mateo, CA"
        )
        block = {
            "company": "Gainwell Technologies",
            "title": "Senior Business Systems Analyst / Senior UAT Lead",
            "date_range": "April 2024 – Present",
            "location": "Remote",
            "bullets": filler + [tesla, "Supported metrics refresh."],
        }
        rows = experience_blocks_to_entries([block])
        _print_entries_indexed(rows, label="structured_embedded_tesla")
        self._assert_no_header_bullets(rows, msg="structured_embedded_tesla")
        self._assert_identity_pipe_lines_not_in_bullets(rows)
        self.assertGreaterEqual(len(rows), 2)
        for b in rows[0].bullets:
            self.assertFalse(_line_looks_like_role_header(b), msg=b)
        self.assertTrue(any("tesla" in (r.company or "").lower() for r in rows[1:]))
        payload = build_resume_document_payload(
            name="Test",
            contact="t@example.com",
            summary="Summary for contract check.",
            summary_source="test",
            experience_blocks=[block],
            projects=[],
            education=[],
            certifications=[],
            skills=["Data & Analytics: SQL"],
        )
        validate_resume_document_payload(payload)

    def test_embedded_three_line_job_header_fragments_in_bullet_stream(self) -> None:
        """
        Date / company / title as separate lines (no pipes) must not remain in the prior
        job's bullets — they synthesize a boundary row for the next employer.
        """
        block = {
            "company": "Tesla",
            "title": "Data Specialist (Autopilot)",
            "date_range": "April 2024 – Present",
            "location": "San Mateo, CA",
            "bullets": [
                "Partnered cross-functionally to validate camera and sensor datasets, identify systemic quality gaps, and standardize review frameworks to improve reliability and downstream model performance.",
                "Leveraged SQL to extract and validate CRM datasets, generate GIA reporting outputs, and simulate SLA boundary conditions by backdating case records for expedited workflow testing.",
                "Reduced rework by 90% by standardizing and documenting test scripts, improving validation consistency and operational efficiency across data review workflows.",
                "Supported Autopilot data validation within a sensor-driven, production-scale environment, ensuring dataset integrity and operational accuracy for real-world driving scenarios.",
                "July 2020 \u2013 June 2022",
                "Gainwell Technologies",
                "Senior Business Systems Analyst / Senior UAT Lead",
                "Mapped cross-department data dependencies and integration points to strengthen end-to-end validation accuracy across interconnected systems.",
                "Data Specialist (Autopilot)",
            ],
        }
        rows = experience_blocks_to_entries([block])
        _print_entries_indexed(rows, label="embedded_fragment_dcr")
        self.assertGreaterEqual(len(rows), 2)
        tesla = rows[0]
        self.assertIn("tesla", (tesla.company or "").lower())
        for b in tesla.bullets:
            self.assertFalse(
                _line_looks_like_role_header(b),
                msg=f"Tesla bullets must not contain job-header-shaped lines: {b!r}",
            )
            self.assertFalse(
                _line_is_embedded_identity_fragment(b),
                msg=f"Tesla bullets must not contain date/company/title fragments: {b!r}",
            )
        self.assertNotIn("gainwell", " ".join(tesla.bullets).lower())
        gainwell = next(r for r in rows if "gainwell" in (r.company or "").lower())
        self.assertIn("senior", (gainwell.role or "").lower())
        self.assertTrue(any("mapped cross-department" in (x or "").lower() for x in gainwell.bullets))
        payload = build_resume_document_payload(
            name="Test",
            contact="t@example.com",
            summary="Summary for contract check.",
            summary_source="test",
            experience_blocks=[block],
            projects=[],
            education=[],
            certifications=[],
            skills=["Data & Analytics: SQL"],
        )
        validate_resume_document_payload(payload)

    def test_trailing_distinct_standalone_role_splits_new_job_from_gainwell(self) -> None:
        """
        A strong standalone title line (e.g. another employer's role) must not remain
        appended to the prior job's bullets — it opens a new entry.
        """
        block = {
            "company": "Gainwell Technologies",
            "title": "Senior Business Systems Analyst / Senior UAT Lead",
            "date_range": "April 2024 – Present",
            "location": "Remote",
            "bullets": [
                "Led client demonstrations for all release phases, refining outputs through iterative feedback until formal acceptance.",
                "Developed a Selenium and Python automation tool to scrape client-facing webpages.",
                "Leveraged SQL to extract and validate CRM datasets, generate GIA reporting outputs, and simulate SLA boundary conditions by backdating case records for expedited workflow testing.",
                "Mapped cross-department data dependencies and integration points to strengthen end-to-end validation accuracy across interconnected systems.",
                "Data Specialist (Autopilot)",
                "Supported Autopilot data validation within a sensor-driven, production-scale environment.",
            ],
        }
        rows = experience_blocks_to_entries([block])
        self.assertGreaterEqual(len(rows), 2)
        gainwell = next(r for r in rows if "gainwell" in (r.company or "").lower())
        tesla = next(
            r
            for r in rows
            if "data specialist" in (r.role or "").lower() and "autopilot" in (r.role or "").lower()
        )
        self.assertNotIn(
            "data specialist",
            " ".join(gainwell.bullets).lower(),
            msg="Gainwell bullets must not contain the Tesla role line",
        )
        self.assertTrue(
            any("autopilot" in (b or "").lower() for b in tesla.bullets),
            msg="Tesla row should own the Autopilot achievement bullet",
        )
        for ei, e in enumerate(rows):
            for j, b in enumerate(e.bullets):
                self.assertFalse(
                    _line_is_embedded_identity_fragment(str(b).strip()),
                    msg=f"fragment leaked experience[{ei}].bullets[{j}]={b!r}",
                )
        payload = build_resume_document_payload(
            name="Test",
            contact="t@example.com",
            summary="Summary for contract check.",
            summary_source="test",
            experience_blocks=[block],
            projects=[],
            education=[],
            certifications=[],
            skills=["Data & Analytics: SQL"],
        )
        validate_resume_document_payload(payload)

    def test_embedded_dcr_with_unicode_minus_in_date_line(self) -> None:
        """Unicode minus (U+2212) in the date fragment must still merge and split cleanly."""
        block = {
            "company": "Tesla",
            "title": "Data Specialist (Autopilot)",
            "date_range": "April 2024 – Present",
            "location": "San Mateo, CA",
            "bullets": [
                "Supported Autopilot validation in production-scale environments.",
                "July 2020\u2212June 2022",
                "Gainwell Technologies",
                "Senior Business Systems Analyst / Senior UAT Lead",
                "Mapped cross-department data dependencies for UAT coverage.",
            ],
        }
        rows = experience_blocks_to_entries([block])
        self.assertGreaterEqual(len(rows), 2)
        tesla = next(r for r in rows if "tesla" in (r.company or "").lower())
        self.assertNotIn("gainwell", " ".join(tesla.bullets).lower())
        payload = build_resume_document_payload(
            name="Test",
            contact="t@example.com",
            summary="Summary for contract check.",
            summary_source="test",
            experience_blocks=[block],
            projects=[],
            education=[],
            certifications=[],
            skills=["Data & Analytics: SQL"],
        )
        validate_resume_document_payload(payload)


if __name__ == "__main__":
    unittest.main()
