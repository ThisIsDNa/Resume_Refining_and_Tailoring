"""
Extract grounded resume signals (strengths, tools, evidence) from ``resume_data`` dicts.

Uses only text present in the payload — no LLM, no invented employers or roles.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.services.gap_analysis.signals_catalog import SIGNAL_CATALOG

# Common tools / platforms (surface string matches only).
_TOOL_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("sql", r"\bsql\b"),
    ("python", r"\bpython\b"),
    ("excel", r"\bexcel\b"),
    ("power bi", r"power\s*bi|powerbi"),
    ("tableau", r"\btableau\b"),
    ("jira", r"\bjira\b"),
    ("confluence", r"\bconfluence\b"),
    ("salesforce", r"\bsalesforce\b"),
    ("azure", r"\bazure\b"),
    ("aws", r"\baws\b"),
    ("snowflake", r"\bsnowflake\b"),
    ("databricks", r"\bdatabricks\b"),
    ("looker", r"\blooker\b"),
    ("r", r"\br\b(?=\s|,|\)|\.)"),
)

_STRENGTH_LINE_RE = re.compile(
    r"(?i)\b(led|drove|owned|delivered|increased|reduced|improved|launched|built|"
    r"achieved|accelerated|scaled|optimized|designed|implemented)\b"
)


def _sections_blob(resume_data: Dict[str, Any]) -> Dict[str, str]:
    """Flatten common resume_data shapes into lowercase section text."""
    sections = resume_data.get("sections") or {}
    out: Dict[str, str] = {}

    def _join_lines(items: Any) -> str:
        if isinstance(items, str):
            return items
        if not isinstance(items, list):
            return ""
        parts: List[str] = []
        for it in items:
            if isinstance(it, str) and it.strip():
                parts.append(it.strip())
            elif isinstance(it, dict):
                for k in ("bullets", "summary", "text", "description"):
                    raw = it.get(k)
                    if isinstance(raw, list):
                        parts.extend(str(x).strip() for x in raw if str(x).strip())
                    elif isinstance(raw, str) and raw.strip():
                        parts.append(raw.strip())
                for k in ("company", "title", "role", "name", "degree", "institution"):
                    v = it.get(k)
                    if isinstance(v, str) and v.strip():
                        parts.append(v.strip())
        return "\n".join(parts)

    out["summary"] = _join_lines(sections.get("summary") or resume_data.get("summary") or "")
    out["experience"] = _join_lines(sections.get("experience") or resume_data.get("experience") or [])
    out["projects"] = _join_lines(sections.get("projects") or resume_data.get("projects") or [])
    out["skills"] = _join_lines(sections.get("skills") or resume_data.get("skills") or [])
    out["education"] = _join_lines(sections.get("education") or resume_data.get("education") or [])
    out["certifications"] = _join_lines(
        sections.get("certifications") or resume_data.get("certifications") or []
    )
    raw = resume_data.get("raw_text")
    if isinstance(raw, str) and raw.strip():
        out["raw_text"] = raw.strip()
    return {k: v for k, v in out.items() if v}


def _best_excerpt(blob: str, needle: str, radius: int = 90) -> str:
    blob_l = blob.lower()
    idx = blob_l.find(needle.lower())
    if idx < 0:
        return (blob[: radius * 2] + ("…" if len(blob) > radius * 2 else "")).strip()
    lo = max(0, idx - radius)
    hi = min(len(blob), idx + len(needle) + radius)
    frag = " ".join(blob[lo:hi].split())
    if lo > 0:
        frag = "…" + frag
    if hi < len(blob):
        frag = frag + "…"
    return frag[:320].strip()


def _strength_level(hit_sections: Dict[str, int], total_hits: int) -> str:
    exp_h = hit_sections.get("experience", 0)
    proj_h = hit_sections.get("projects", 0)
    if exp_h >= 2 or (exp_h >= 1 and total_hits >= 4):
        return "strong"
    if exp_h >= 1 or proj_h >= 2 or total_hits >= 3:
        return "moderate"
    return "thin"


def extract_resume_signals(resume_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return structured JSON:
    - strengths: short bullet-derived lines showing outcomes/ownership language
    - tools: detected tool tokens (grounded in text)
    - evidence_signals: catalog signals with strength_level + excerpt from resume
    """
    blobs = _sections_blob(resume_data)
    combined = "\n".join(blobs.values()).lower()
    if not combined.strip():
        return {"strengths": [], "tools": [], "evidence_signals": []}

    strengths: List[str] = []
    exp_text = blobs.get("experience", "").lower()
    if exp_text:
        for line in exp_text.splitlines():
            t = line.strip()
            if len(t) < 28:
                continue
            if _STRENGTH_LINE_RE.search(t):
                strengths.append(line.strip()[:220])
            if len(strengths) >= 6:
                break

    tools: List[str] = []
    for label, pattern in _TOOL_PATTERNS:
        if re.search(pattern, combined, re.I):
            tools.append(label)
    tools = sorted(set(tools))

    evidence: List[Dict[str, Any]] = []
    for signal_id, spec in SIGNAL_CATALOG.items():
        hit_sections: Dict[str, int] = {}
        total = 0
        first_needle = ""
        first_blob_name = ""
        first_blob = ""
        for sec, text in blobs.items():
            if not text:
                continue
            tl = text.lower()
            for kw in spec["keywords"]:
                if kw.lower() in tl:
                    hit_sections[sec] = hit_sections.get(sec, 0) + tl.count(kw.lower())
                    total += tl.count(kw.lower())
                    if not first_needle:
                        first_needle = kw
                        first_blob_name = sec
                        first_blob = text
        if total == 0:
            continue
        excerpt = _best_excerpt(first_blob, first_needle) if first_blob else ""
        evidence.append(
            {
                "signal_id": signal_id,
                "label": spec["label"],
                "strength_level": _strength_level(hit_sections, total),
                "source_section": first_blob_name or "unknown",
                "excerpt": excerpt,
            }
        )

    evidence.sort(key=lambda x: (-{"strong": 3, "moderate": 2, "thin": 1}[str(x["strength_level"])]))
    return {"strengths": strengths, "tools": tools, "evidence_signals": evidence}
