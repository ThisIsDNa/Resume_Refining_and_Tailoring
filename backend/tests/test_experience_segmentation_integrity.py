"""
Targeted segmentation integrity check: one sealed job per entry before prioritization/render.

Run: python -m unittest tests.test_experience_segmentation_integrity -v
"""

from __future__ import annotations

import logging
import sys
import unittest

from app.services.resume_document_assembly import (
    ExperienceEntry,
    _count_company_identity_chunks_in_company_field,
    _count_distinct_date_spans_in_header_metadata,
    _line_looks_like_role_header,
    build_resume_document_payload,
    experience_blocks_to_entries,
    log_experience_segmentation_audit,
    validate_resume_document_payload,
)

# Re-use fixture aligned with product examples (one unstructured block, three job headers).
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


def _print_final_segmented_entries(entries: list[ExperienceEntry], *, label: str) -> None:
    print(f"\n{'=' * 72}", file=sys.stderr)
    print(f"FINAL SEGMENTED EXPERIENCE ENTRIES ({label})", file=sys.stderr)
    print(f"{'=' * 72}", file=sys.stderr)
    for i, e in enumerate(entries):
        n_spans = _count_distinct_date_spans_in_header_metadata(e.date, e.location)
        n_co = _count_company_identity_chunks_in_company_field(e.company or "")
        print(f"\n[{i}]", file=sys.stderr)
        print(f"  company : {e.company!r}", file=sys.stderr)
        print(f"  role    : {e.role!r}", file=sys.stderr)
        print(f"  date    : {e.date!r}", file=sys.stderr)
        print(f"  location: {e.location!r}", file=sys.stderr)
        print(f"  bullets ({len(e.bullets)}):", file=sys.stderr)
        for j, b in enumerate(e.bullets):
            print(f"    - [{j}] {b!r}", file=sys.stderr)
        print(
            f"  metrics: date_span_count={n_spans} company_like_chunks={n_co}",
            file=sys.stderr,
        )
    print(file=sys.stderr)


class TestExperienceSegmentationIntegrity(unittest.TestCase):
    """Sanity: distinct sealed entries, no cross-job contamination, validator unchanged."""

    def test_segmentation_integrity_three_jobs_print_and_assert(self) -> None:
        logging.basicConfig(
            level=logging.INFO,
            stream=sys.stderr,
            format="%(message)s",
            force=True,
        )

        blocks = [THREE_JOB_BLOCK]

        entries = experience_blocks_to_entries(blocks)
        # Same ordering as build_resume_document_payload: audit then validate.
        log_experience_segmentation_audit(blocks, entries)
        _print_final_segmented_entries(entries, label="after experience_blocks_to_entries")

        self.assertEqual(
            len(entries),
            3,
            "entry count must match three jobs in the fixture",
        )

        # Per-entry structural invariants (sealed header metadata).
        for i, e in enumerate(entries):
            self.assertTrue(
                (e.company or "").strip() or (e.role or "").strip(),
                f"entry[{i}] must have company or role",
            )
            self.assertLessEqual(
                _count_company_identity_chunks_in_company_field(e.company or ""),
                1,
                f"entry[{i}] must not concatenate multiple company labels: company={e.company!r}",
            )
            n_spans = _count_distinct_date_spans_in_header_metadata(e.date, e.location)
            self.assertEqual(
                n_spans,
                1,
                f"entry[{i}] must have exactly one date range in header metadata "
                f"(date={e.date!r} location={e.location!r})",
            )
            self.assertNotIn(
                "|",
                (e.role or ""),
                f"entry[{i}] role must be a single identity, not pipe-merged: {e.role!r}",
            )
            for j, b in enumerate(e.bullets):
                self.assertFalse(
                    _line_looks_like_role_header(b),
                    f"entry[{i}] bullet[{j}] must not be a job header line: {b!r}",
                )

        # Expected identities (Gainwell → Tesla → RWS).
        g, t, r = entries[0], entries[1], entries[2]

        self.assertEqual(g.company.strip(), "Gainwell Technologies")
        self.assertEqual(
            g.role.strip(),
            "Senior Business Systems Analyst / Senior UAT Lead",
        )
        # Pipe-style headers: span extraction keeps the core range (often "2024 – Present"), not
        # necessarily the full "April 2024 – Present" substring from the raw line. Segmentation
        # integrity here is single-span + correct job-bound bullets, not month-prefix fidelity.
        self.assertIn("2024", g.date)
        self.assertIn("Present", g.date)
        self.assertEqual(g.location.strip(), "Remote")
        self.assertEqual(g.bullets, ["Led UAT for Provider Portal."])

        self.assertEqual(t.company.strip(), "Tesla")
        self.assertEqual(t.role.strip(), "Data Specialist (Autopilot)")
        self.assertIn("July 2020", t.date)
        self.assertIn("June 2022", t.date)
        self.assertEqual(t.location.strip(), "San Mateo, CA")
        self.assertEqual(t.bullets, ["Supported Autopilot data pipelines."])

        self.assertIn("RWS", r.company)
        self.assertIn("Apple", r.company)
        self.assertEqual(r.role.strip(), "Business Data Technician")
        self.assertIn("June 2019", r.date)
        self.assertIn("June 2020", r.date)
        self.assertEqual(r.location.strip(), "Sunnyvale, CA")
        self.assertEqual(r.bullets, ["Maintained localization data workflows."])

        # No bullet leakage across jobs (distinctive employer/title tokens).
        joined0 = "\n".join(g.bullets).lower()
        joined1 = "\n".join(t.bullets).lower()
        joined2 = "\n".join(r.bullets).lower()
        self.assertNotIn("tesla", joined0)
        self.assertNotIn("rws", joined0)
        self.assertNotIn("gainwell", joined1)
        self.assertNotIn("rws", joined1)
        self.assertNotIn("gainwell", joined2)
        self.assertNotIn("tesla", joined2)

        # Full payload: audit hook + validator (no rule weakening).
        payload = build_resume_document_payload(
            name="Test User",
            contact="test@example.com",
            summary="Summary.",
            summary_source="test",
            experience_blocks=blocks,
            projects=[],
            education=[],
            certifications=[],
            skills=["SQL"],
        )
        self.assertEqual(len(payload.experience), 3)
        _print_final_segmented_entries(payload.experience, label="from build_resume_document_payload")
        validate_resume_document_payload(payload)
