"""Explainable score breakdown derived from visible evidence (no opaque scores)."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.services.parse_job import requirement_allowed_in_pipeline


def _keyword_evidence_hit(keyword: str, evidence_blob: str) -> bool:
    """Reduce substring noise for short tokens (e.g. sql, bi, aws) while keeping deterministic checks."""
    k = keyword.lower().strip()
    if len(k) < 2:
        return False
    if len(k) <= 5:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", evidence_blob))
    return k in evidence_blob

def _evidence_text_for_keyword_alignment(mapping_result: Dict[str, Any], job_signals: Dict[str, Any]) -> str:
    """Derive searchable text from user-facing mapping output (no diagnostic fields)."""
    parts: List[str] = []
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict):
            continue
        if not requirement_allowed_in_pipeline(str(row.get("requirement_text") or ""), job_signals):
            continue
        for ev in row.get("matched_evidence") or []:
            if isinstance(ev, dict) and ev.get("text"):
                parts.append(str(ev["text"]))
    return " ".join(parts).lower()


def compute_explainable_score(
    mapping_result: dict, rewrite_result: dict, job_signals: dict
) -> dict:
    """
    Deterministic breakdown: requirement coverage, gaps, evidence strength, keyword alignment.
    """
    raw_matches = mapping_result.get("requirement_matches") or []
    matches: List[Any] = []
    if isinstance(raw_matches, list):
        matches = [
            m
            for m in raw_matches
            if isinstance(m, dict)
            and requirement_allowed_in_pipeline(str(m.get("requirement_text") or ""), job_signals)
        ]
    if isinstance(matches, list) and matches and isinstance(matches[0], dict):
        strong = sum(1 for m in matches if m.get("classification") == "strong")
        weak = sum(1 for m in matches if m.get("classification") == "weak")
        missing = sum(1 for m in matches if m.get("classification") == "missing")
    elif isinstance(matches, dict):
        strong = len(matches.get("matched") or [])
        weak = len(matches.get("weak") or [])
        missing = len(matches.get("missing") or [])
    else:
        strong, weak, missing = 0, 0, 0
    total = strong + weak + missing
    if total == 0:
        total = 1

    requirement_coverage = min(100, round(100 * strong / total))
    if strong >= 4:
        requirement_coverage = min(100, requirement_coverage + 8)
    elif strong >= 2:
        requirement_coverage = min(100, requirement_coverage + 4)

    keywords = [k.lower() for k in (job_signals.get("keywords") or []) if k]
    gaps_list = mapping_result.get("gaps") or []
    parse_warn = any(
        "could not be fully parsed" in str(g).lower() for g in (gaps_list if isinstance(gaps_list, list) else [])
    )
    # Align gap pressure with validated requirement rows only (not raw gap string cardinality).
    gap_count = int(missing) + (1 if parse_warn else 0)

    # Keyword alignment: JD keywords vs matched evidence text (from requirement_matches only)
    evidence_blob = _evidence_text_for_keyword_alignment(mapping_result, job_signals)
    if not evidence_blob.strip():
        evidence_blob = (
            (rewrite_result.get("tailored_summary") or "")
            + " "
            + " ".join(rewrite_result.get("tailored_experience_bullets") or [])
        ).lower()

    if keywords:
        hits = sum(1 for k in keywords if _keyword_evidence_hit(k, evidence_blob))
        keyword_alignment = min(100, round(100 * hits / max(len(keywords), 1)))
    else:
        keyword_alignment = 50

    n_bullets = len(rewrite_result.get("tailored_experience_bullets") or [])
    evidence_strength = min(
        100,
        int(28 + min(n_bullets, 5) * 10 + strong * 3 + weak * 1),
    )

    gap_penalty = min(
        100,
        int(12 + 10 * missing + 4 * weak + min(gap_count, 8) * 2),
    )

    overall = int(
        requirement_coverage * 0.38
        + keyword_alignment * 0.22
        + evidence_strength * 0.28
        - gap_penalty * 0.12
    )
    strong_fit_nudge = min(14, strong * 2 + max(0, strong - missing))
    overall = overall + strong_fit_nudge

    # Separate “almost no clear fit” from “several clear overlaps” without changing the core rubric much.
    if strong <= 1 and missing >= 5:
        overall -= min(16, 6 + (missing - 5) * 2)
    if strong >= 4 and missing <= max(4, strong + 1):
        overall += min(8, (strong - 3) * 2)

    overall = max(0, min(100, overall))

    if keyword_alignment <= 10:
        kw_line = (
            "Term overlap with extracted job keywords is modest in the lines we could match — "
            "useful signal, not a completeness score."
        )
    else:
        kw_line = (
            f"Term overlap: about {keyword_alignment}% of extracted job keywords appear in lines we could match "
            f"to your resume — useful signal, not a completeness score."
        )

    notes: List[str] = [
        (
            f"Coverage snapshot: {strong} clear overlaps, {weak} partial, {missing} not evidenced "
            f"across {strong + weak + missing} stated needs from the posting."
        ),
        kw_line,
        (
            "Evidence strength nudges up when matched lines look concrete and recent; "
            "it is a guide for where to tighten, not a hiring prediction."
        ),
    ]

    return {
        "overall_score": overall,
        "dimensions": {
            "requirement_coverage": int(requirement_coverage),
            "keyword_alignment": int(keyword_alignment),
            "evidence_strength": int(evidence_strength),
            "gap_penalty": int(gap_penalty),
        },
        "summary": {
            "matched_requirements": strong,
            "weak_matches": weak,
            "missing_requirements": missing,
        },
        "notes": notes,
    }
