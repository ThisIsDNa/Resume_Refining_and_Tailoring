"""
Targeted sanity: embedded date/company/title fragments inside experience bullets.

Run from the backend directory:
  python scripts/run_streaming_segmentation_sanity.py
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.resume_document_assembly import (  # noqa: E402
    _line_is_embedded_identity_fragment,
    build_resume_document_payload,
    experience_blocks_to_entries,
    streaming_segmentation_trace,
    validate_resume_document_payload,
)

# Structured Tesla + embedded Gainwell D/C/R fragment + trailing duplicate title.
PROBLEMATIC_BLOCK = {
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


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", (s or "").strip())


def _is_embedded_header_fragment_event(ev: Dict[str, Any]) -> bool:
    """True when this trace row represents material from a multi-line embedded job header."""
    action = str(ev.get("action") or "")
    if action == "fragment_component":
        return True
    if action == "synthesize_pipe_header":
        return True
    if action == "drop_redundant_first_header_role_repeat":
        return True
    if action.startswith("queue_pop_embedded"):
        return True
    return False


def _print_trace_table(trace: List[Dict[str, Any]]) -> None:
    print("=== BULLET-STREAM SEGMENTATION TRACE ===\n")
    print(
        f"{'#':>3}  {'phase':^10}  {'ix':>3}  "
        f"{'detected':^18}  {'embedded_frag':^14}  {'action':^34}  raw_line"
    )
    print("-" * 140)
    for n, ev in enumerate(trace):
        rl = str(ev.get("raw_line") or "")
        preview = rl.replace("\n", " ")
        if len(preview) > 72:
            preview = preview[:69] + "..."
        emb = "yes" if _is_embedded_header_fragment_event(ev) else "no"
        print(
            f"{n:>3}  {str(ev.get('phase')):^10}  {int(ev.get('line_index', -1)):>3}  "
            f"{str(ev.get('detected')):^18}  {emb:^14}  {str(ev.get('action')):^34}  {preview!r}"
        )
    print()


def main() -> int:
    block = PROBLEMATIC_BLOCK
    leading = " | ".join(
        str(x).strip()
        for x in (
            block["company"],
            block["title"],
            block["date_range"],
            block["location"],
        )
        if str(x).strip()
    )
    raw_bullets = [str(b).strip() for b in (block.get("bullets") or []) if str(b).strip()]
    stream = [leading] + raw_bullets

    trace, raw_entries = streaming_segmentation_trace(
        stream,
        block_date="",
        block_location="",
    )

    # --- Check 1: trace ---
    _print_trace_table(trace)

    forbidden = [
        "July 2020 – June 2022",
        "July 2020 \u2013 June 2022",
        "Gainwell Technologies",
        "Senior Business Systems Analyst / Senior UAT Lead",
        "Data Specialist (Autopilot)",
    ]
    forbidden_n = {_nfkc(x) for x in forbidden}

    print("=== RAW SEGMENTER OUTPUT (pre-finalize, synthetic stream) ===\n")
    for i, ent in enumerate(raw_entries):
        print(f"--- raw entry[{i}] company={ent.company!r} role={ent.role!r} ---")
        for j, b in enumerate(ent.bullets):
            print(f"  bullet[{j}] {b!r}")
        print()

    # --- Check 2: forbidden lines never appended as bullets in scan ---
    scan_appends = [
        ev
        for ev in trace
        if ev.get("phase") == "scan" and ev.get("action") == "append_bullet"
    ]
    bad_scan = [ev for ev in scan_appends if _nfkc(str(ev.get("raw_line") or "")) in forbidden_n]
    print("=== CHECK 2: forbidden lines must NOT survive in bullets (scan append_bullet) ===")
    if bad_scan:
        for ev in bad_scan:
            print("FAIL:", ev)
        return 1
    print("OK: none of the forbidden lines were appended as bullets during scan.\n")

    # --- Check 3: Tesla entry closed before embedded fragment becomes next job ---
    st = [ev for ev in trace if ev.get("phase") == "scan"]
    tesla_company = "tesla"
    last_tesla_bullet_ix = -1
    first_close_before_gainwell_ix = -1
    for idx, ev in enumerate(st):
        if ev.get("action") == "append_bullet" and tesla_company in str(ev.get("cur_company", "")).lower():
            last_tesla_bullet_ix = idx
        if (
            ev.get("action") == "close_entry"
            and idx + 1 < len(st)
            and st[idx + 1].get("action") == "start_new_entry"
            and "gainwell" in str(st[idx + 1].get("raw_line", "")).lower()
        ):
            first_close_before_gainwell_ix = idx
            break
    print("=== CHECK 3: Tesla entry closed before embedded fragment (next job) ===")
    if first_close_before_gainwell_ix < 0:
        print("FAIL: no close_entry immediately before Gainwell start_new_entry.")
        return 1
    if last_tesla_bullet_ix >= 0 and last_tesla_bullet_ix > first_close_before_gainwell_ix:
        print(
            "FAIL: Tesla append_bullet after close_entry "
            f"(last_tesla_bullet_scan_ix={last_tesla_bullet_ix}, close_ix={first_close_before_gainwell_ix})."
        )
        return 1
    print(
        "OK: close_entry precedes Gainwell start_new_entry; "
        f"last Tesla append_bullet at scan-event index {last_tesla_bullet_ix} "
        f"before close at {first_close_before_gainwell_ix}.\n"
    )

    # --- Check 4: new Gainwell entry from synthesized fragment header ---
    gainwell_starts = [
        ev
        for ev in st
        if ev.get("action") == "start_new_entry"
        and "gainwell" in str(ev.get("raw_line", "")).lower()
    ]
    print("=== CHECK 4: new Gainwell entry starts from embedded fragment ===")
    if not gainwell_starts:
        print("FAIL: no start_new_entry with Gainwell in synthetic header line.")
        return 1
    print(f"OK: Gainwell boundary observed ({len(gainwell_starts)} matching start_new_entry).\n")

    final_rows = experience_blocks_to_entries([block])
    tesla = next(e for e in final_rows if "tesla" in (e.company or "").lower())
    gainwell = next(e for e in final_rows if "gainwell" in (e.company or "").lower())

    print("=== CHECK 5: final bullets - no standalone date/company/title fragments ===")
    tb = " ".join(tesla.bullets).lower()
    gb = " ".join(gainwell.bullets).lower()
    if "gainwell" in tb or "mapped cross-department" in tb:
        print("FAIL: Tesla bullets contain Gainwell-specific content.")
        return 1
    if "mapped cross-department" not in gb:
        print("FAIL: Gainwell bullets should include the post-boundary achievement.")
        return 1
    for ei, e in enumerate(final_rows):
        for j, b in enumerate(e.bullets):
            bt = str(b).strip()
            if _line_is_embedded_identity_fragment(bt):
                print(f"FAIL: experience[{ei}].bullets[{j}] fragment={bt!r}")
                return 1
            if _nfkc(bt) in forbidden_n:
                print(f"FAIL: experience[{ei}].bullets[{j}] forbidden line={bt!r}")
                return 1
    print("OK: no forbidden or fragment-detected lines in any entry's final bullets.\n")

    print("=== CHECK 6: validate_resume_document_payload (rules unchanged) ===")
    payload = build_resume_document_payload(
        name="Streaming sanity",
        contact="sanity@example.com",
        summary="Summary for contract check.",
        summary_source="sanity_script",
        experience_blocks=[block],
        projects=[],
        education=[],
        certifications=[],
        skills=["Data & Analytics: SQL"],
    )
    validate_resume_document_payload(payload)
    print("OK: validation passed.\n")

    print("All embedded header-fragment splitting sanity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
