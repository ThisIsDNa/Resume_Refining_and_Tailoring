"""
Sanity: orphan bullet repair — provisional segmentation vs post-merge sealed entries.

Run: python -m unittest tests.test_orphan_bullet_repair_sanity -v
"""

from __future__ import annotations

import logging
import sys
import unittest

from app.services.resume_document_assembly import (
    ExperienceEntry,
    HeaderCanonical,
    ResumeDocumentPayload,
    _finalize_experience_entries_sealed,
    experience_blocks_to_entries,
    experience_blocks_to_provisional_entries,
    merge_pure_orphan_bullet_entries_into_adjacent_identity,
    validate_resume_document_payload,
)

# Mirrors the list shape after per-block assembly when a bullet-only row precedes structured Gainwell
# (same merge the export path applies). A bullet-only API block with no header line cannot be
# segmented alone; this fixture exercises repair + validation directly.
PROVISIONAL_ORPHAN_THEN_GAINWELL_TESLA_RWS: list[ExperienceEntry] = [
    ExperienceEntry(
        "",
        "",
        "",
        "",
        [
            "Resolved 50+ overdue SLA deliverables across cross-functional teams.",
            "Frequently placed into ambiguous, undocumented environments requiring rapid discovery.",
            "Lead end-to-end functional validation aligning business rules with technical delivery.",
        ],
    ),
    ExperienceEntry(
        "Gainwell Technologies",
        "Senior Business Systems Analyst / Senior UAT Lead",
        "April 2024 – Present",
        "Remote",
        [],
    ),
    ExperienceEntry(
        "Tesla",
        "Data Specialist (Autopilot)",
        "July 2020 – June 2022",
        "San Mateo, CA",
        ["Tesla-only evidence: Autopilot data pipeline support."],
    ),
    ExperienceEntry(
        "RWS Moravia (Client: Apple)",
        "Business Data Technician",
        "June 2019 – June 2020",
        "Sunnyvale, CA",
        ["RWS-only evidence: localization data workflows."],
    ),
]


def _print_entries(label: str, entries: list[ExperienceEntry]) -> None:
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}", file=sys.stderr)
    for i, e in enumerate(entries):
        print(
            f"[{i}] company={e.company!r} role={e.role!r} date={e.date!r} "
            f"location={e.location!r} bullet_count={len(e.bullets)}",
            file=sys.stderr,
        )
        for j, b in enumerate(e.bullets[:8]):
            print(f"      bullet[{j}] {b[:100]!r}{'...' if len(b) > 100 else ''}", file=sys.stderr)
        if len(e.bullets) > 8:
            print(f"      ... +{len(e.bullets) - 8} more", file=sys.stderr)


class TestOrphanBulletRepairSanity(unittest.TestCase):
    def test_provisional_then_repair_then_validate(self) -> None:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s", force=True)

        provisional = [ExperienceEntry(e.company, e.role, e.date, e.location, list(e.bullets)) for e in PROVISIONAL_ORPHAN_THEN_GAINWELL_TESLA_RWS]
        _print_entries("PROVISIONAL (segmented before orphan repair)", provisional)

        self.assertTrue(
            provisional[0].bullets and not (provisional[0].company or "").strip() and not (provisional[0].role or "").strip(),
            "fixture[0] must be bullet-only to mirror the failure mode",
        )

        repaired = merge_pure_orphan_bullet_entries_into_adjacent_identity(provisional)
        final = _finalize_experience_entries_sealed(repaired)

        _print_entries("FINAL (after orphan repair + seal, before payload validation)", final)

        for i, e in enumerate(final):
            if e.bullets:
                self.assertTrue(
                    (e.company or "").strip() or (e.role or "").strip(),
                    f"entry[{i}] must not have bullets with empty company and role",
                )

        self.assertEqual(len(final), 3, "orphan folded into Gainwell; Tesla and RWS stay separate")

        g = final[0]
        self.assertEqual(g.company.strip(), "Gainwell Technologies")
        self.assertEqual(g.role.strip(), "Senior Business Systems Analyst / Senior UAT Lead")
        self.assertEqual(g.date.strip(), "April 2024 – Present")
        self.assertEqual(g.location.strip(), "Remote")

        joined = "\n".join(g.bullets)
        self.assertIn("Resolved 50+ overdue SLA", joined)
        self.assertIn("Frequently placed into ambiguous", joined)
        self.assertIn("Lead end-to-end functional validation", joined)

        t = final[1]
        r = final[2]
        self.assertEqual(t.company.strip(), "Tesla")
        self.assertNotIn("Resolved 50+", "\n".join(t.bullets))
        self.assertNotIn("Lead end-to-end functional validation", "\n".join(t.bullets))
        self.assertIn("Autopilot", "\n".join(t.bullets))

        self.assertIn("RWS", r.company)
        self.assertNotIn("Resolved 50+", "\n".join(r.bullets))
        self.assertNotIn("Tesla-only", "\n".join(r.bullets))

        payload = ResumeDocumentPayload(
            header=HeaderCanonical(name="N", contact="c"),
            summary="S",
            summary_source="t",
            experience=final,
            projects=[],
            education=[],
            certifications=[],
            skills=["SQL"],
        )
        validate_resume_document_payload(payload)

    def test_provisional_matches_pipeline_when_all_blocks_have_identity(self) -> None:
        """No orphan rows: provisional segment count matches final after merge (no-op repair)."""
        blocks = [
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
        ]
        prov = experience_blocks_to_provisional_entries(blocks)
        final = experience_blocks_to_entries(blocks)
        self.assertEqual(len(prov), len(final), "no orphan merge when every block is structured")
        self.assertEqual(len(final), 2)
        validate_resume_document_payload(
            ResumeDocumentPayload(
                header=HeaderCanonical(name="N", contact="c"),
                summary="S",
                summary_source="t",
                experience=final,
                projects=[],
                education=[],
                certifications=[],
                skills=[],
            )
        )
