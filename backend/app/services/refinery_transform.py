"""
Refinery-only resume tweaks from gap analysis (no JD tailoring, no new employers).

``apply_refinery_actions`` interprets coach strings in ``actions.resume_changes`` (**role labels**)
plus ``gaps.classified`` rows, maps labels to ``SIGNAL_CATALOG`` entries, then tightens existing
bullets using phrases already present elsewhere in the resume (skills, other bullets, summary).
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.gap_analysis.signals_catalog import SIGNAL_CATALOG
from app.services.parse_job import is_actionable_requirement_line

# Grounded stub requirement for export shims (passes actionable requirement gates; not shown in DOCX).
_REFINERY_EXPORT_ANCHOR_REQUIREMENT = (
    "Lead cross-functional teams to deliver enterprise software solutions "
    "with regulatory compliance and documented validation."
)


def _signal_id_for_catalog_label(label: str) -> Optional[str]:
    lnorm = re.sub(r"\s+", " ", (label or "").strip().lower())
    if not lnorm:
        return None
    for sid, spec in SIGNAL_CATALOG.items():
        if str(spec.get("label") or "").strip().lower() == lnorm:
            return sid
    return None


def _signal_ids_from_gap_result(gap_analysis_result: Dict[str, Any]) -> List[str]:
    ordered: List[str] = []
    seen: Set[str] = set()
    actions = gap_analysis_result.get("actions") or {}
    for line in actions.get("resume_changes") or []:
        for m in re.finditer(r"\*\*([^*]+)\*\*", str(line)):
            sid = _signal_id_for_catalog_label(m.group(1))
            if sid and sid not in seen:
                seen.add(sid)
                ordered.append(sid)
    for row in (gap_analysis_result.get("gaps") or {}).get("classified") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("gap_category") or "") != "resume_fixable":
            continue
        sid = str(row.get("signal_id") or "").strip()
        if sid and sid in SIGNAL_CATALOG and sid not in seen:
            seen.add(sid)
            ordered.append(sid)
    return ordered


def _sections_dict(resume_data: Dict[str, Any]) -> Dict[str, Any]:
    sec = resume_data.get("sections")
    return sec if isinstance(sec, dict) else {}


def _all_donor_lines(sections: Dict[str, Any], resume_data: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for block in sections.get("experience") or []:
        if not isinstance(block, dict):
            continue
        for b in block.get("bullets") or []:
            t = str(b).strip()
            if t:
                lines.append(t)
    for proj in sections.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        for b in proj.get("bullets") or []:
            t = str(b).strip()
            if t:
                lines.append(t)
    for s in sections.get("skills") or []:
        if isinstance(s, str) and s.strip():
            lines.append(s.strip())
    summ = sections.get("summary")
    if isinstance(summ, list):
        for s in summ:
            if isinstance(s, str) and s.strip():
                lines.append(s.strip())
    elif isinstance(summ, str) and summ.strip():
        lines.append(summ.strip())
    raw = resume_data.get("raw_text")
    if isinstance(raw, str) and raw.strip():
        for ln in raw.splitlines():
            t = ln.strip()
            if len(t) > 8:
                lines.append(t)
    return lines


def _corpus_lower(sections: Dict[str, Any], resume_data: Dict[str, Any]) -> str:
    parts: List[str] = []
    for ln in _all_donor_lines(sections, resume_data):
        parts.append(ln.lower())
    raw = resume_data.get("raw_text")
    if isinstance(raw, str):
        parts.append(raw.lower())
    return "\n".join(parts)


def _iter_bullet_targets(
    sections: Dict[str, Any],
) -> List[Tuple[str, int, int, str]]:
    out: List[Tuple[str, int, int, str]] = []
    for ei, block in enumerate(sections.get("experience") or []):
        if not isinstance(block, dict):
            continue
        for bi, b in enumerate(block.get("bullets") or []):
            t = str(b).strip()
            if t:
                out.append(("experience", ei, bi, t))
    for pi, proj in enumerate(sections.get("projects") or []):
        if not isinstance(proj, dict):
            continue
        for bi, b in enumerate(proj.get("bullets") or []):
            t = str(b).strip()
            if t:
                out.append(("project", pi, bi, t))
    return out


def _bullet_keyword_hits(keywords: Tuple[str, ...], bullet_lower: str) -> int:
    n = 0
    for kw in keywords:
        k = kw.strip().lower()
        if len(k) < 2:
            continue
        if k in bullet_lower:
            n += 1
    return n


def _pick_target_bullet(
    keywords: Tuple[str, ...], targets: List[Tuple[str, int, int, str]]
) -> Optional[Tuple[str, int, int, str]]:
    if not targets:
        return None
    kws = sorted(keywords, key=lambda x: -len(x.strip()))
    scored: List[Tuple[int, Tuple[int, int, int], str, int, int, str]] = []
    for kind, ei, bi, text in targets:
        low = text.lower()
        hits = _bullet_keyword_hits(tuple(kws), low)
        kind_pri = (0 if kind == "experience" else 1, ei, bi)
        scored.append((hits, kind_pri, kind, ei, bi, text))
    positive = [x for x in scored if x[0] > 0]
    if positive:
        # Thinnest grounded line first (fewest keyword hits), then experience, stable order.
        positive.sort(key=lambda x: (x[0], x[1]))
        _, _, kind, ei, bi, text = positive[0]
        return (kind, ei, bi, text)
    scored.sort(key=lambda x: x[1])
    _, _, kind, ei, bi, text = scored[0]
    return (kind, ei, bi, text)


def _donor_snippet_for_keyword(
    donor_lines: List[str],
    kw: str,
    exclude_norm: str,
    *,
    max_len: int = 110,
) -> str:
    kl = kw.strip().lower()
    if len(kl) < 2:
        return ""
    for d in donor_lines:
        raw = str(d).strip()
        if not raw:
            continue
        if re.sub(r"\s+", " ", raw.lower()) == exclude_norm:
            continue
        low = raw.lower()
        i = low.find(kl)
        if i < 0:
            continue
        if len(raw) <= max_len:
            return raw
        lo = max(0, i - 40)
        hi = min(len(raw), i + len(kw) + 50)
        frag = " ".join(raw[lo:hi].split())
        return frag[:max_len].strip()
    return ""


def _set_bullet(
    sections: Dict[str, Any],
    kind: str,
    ei_or_pi: int,
    bi: int,
    new_text: str,
) -> None:
    if kind == "experience":
        blocks = sections.get("experience") or []
        block = blocks[ei_or_pi]
        bullets = list(block.get("bullets") or [])
        bullets[bi] = new_text
        block["bullets"] = bullets
    else:
        rows = sections.get("projects") or []
        proj = rows[ei_or_pi]
        bullets = list(proj.get("bullets") or [])
        bullets[bi] = new_text
        proj["bullets"] = bullets


def apply_refinery_actions(
    resume_data: Dict[str, Any],
    gap_analysis_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a deep-copied resume_data with at most a few existing bullets augmented.

    Uses ``actions.resume_changes`` (bold catalog labels) and resume-fixable ``gaps.classified``
    rows to choose ``signal_id`` targets. Augmentations are substrings taken from other lines in
    the same resume (never free-form invented metrics or employers).
    """
    out = copy.deepcopy(resume_data)
    sections = _sections_dict(out)
    if not sections:
        return out

    signal_ids = _signal_ids_from_gap_result(gap_analysis_result)
    if not signal_ids:
        return out

    corpus_lower = _corpus_lower(sections, out)
    donor_lines = _all_donor_lines(sections, out)
    targets = _iter_bullet_targets(sections)
    touched: Set[Tuple[str, int, int]] = set()
    max_bullet_touch = 5

    for sid in signal_ids[:8]:
        if len(touched) >= max_bullet_touch:
            break
        spec = SIGNAL_CATALOG.get(sid)
        if not spec:
            continue
        keywords = tuple(spec.get("keywords") or ())
        if not keywords:
            continue
        remaining = [t for t in targets if (t[0], t[1], t[2]) not in touched]
        picked = _pick_target_bullet(keywords, remaining)
        if not picked:
            continue
        kind, ei, bi, bullet_text = picked
        key = (kind, ei, bi)
        bullet_lower = bullet_text.lower()
        exclude_norm = re.sub(r"\s+", " ", bullet_lower).strip()

        # Prefer longer keywords first when surfacing missing tokens already present elsewhere.
        k_sorted = sorted(
            (k for k in keywords if len(k.strip()) >= 3),
            key=lambda x: -len(x.strip()),
        )
        to_add_kw: Optional[str] = None
        for kw in k_sorted:
            kl = kw.strip().lower()
            if len(kl) < 3:
                continue
            if kl in bullet_lower:
                continue
            if kl not in corpus_lower:
                continue
            to_add_kw = kw
            break
        if not to_add_kw:
            continue

        snip = _donor_snippet_for_keyword(donor_lines, to_add_kw, exclude_norm)
        if not snip:
            continue
        snip_low = snip.lower()
        if snip_low in bullet_lower:
            continue

        merged = bullet_text.rstrip()
        merged = merged.rstrip(".") + "; " + snip.strip()
        if len(merged) > 420:
            merged = merged[:420].rstrip() + "."
        if merged.lower().strip() == bullet_lower:
            continue

        _set_bullet(sections, kind, ei, bi, merged)
        touched.add(key)
        # Refresh donor lines and targets for subsequent passes
        donor_lines = _all_donor_lines(sections, out)
        targets = _iter_bullet_targets(sections)

    return out


def _first_experience_evidence_id(resume_data: Dict[str, Any]) -> str:
    sections = _sections_dict(resume_data)
    for ei, block in enumerate(sections.get("experience") or []):
        if not isinstance(block, dict):
            continue
        bullets = block.get("bullets") or []
        if isinstance(bullets, list) and bullets:
            return f"exp_{ei + 1}_bullet_1"
    return "exp_1_bullet_1"


def build_refinery_export_shims(
    resume_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Minimal Tailor-shaped dicts so ``build_export_docx_package`` can run without invoking
    map/rewrite/score pipelines. Requirement text is a fixed, actionable line (not JD-derived).
    """
    req = _REFINERY_EXPORT_ANCHOR_REQUIREMENT
    if not is_actionable_requirement_line(req):
        raise RuntimeError("Refinery export anchor requirement failed actionable gate.")

    eid = _first_experience_evidence_id(resume_data)
    job_signals: Dict[str, Any] = {
        "validated_requirements": [req],
        "validated_requirement_priorities": ["preferred"],
        "must_have_requirements": [],
        "preferred_requirements": [req],
        "keywords": ["compliance", "cross-functional", "validation", "software", "delivery"],
        "role_focus": ["Analytics"],
    }
    mapping_result = {
        "requirement_matches": [
            {
                "requirement_text": req,
                "classification": "strong",
                "priority": "preferred",
                "matched_evidence": [{"id": eid}],
            }
        ]
    }
    score_result = {"overall_score": 68, "summary": {"matched_requirements": 3}}
    rewrite_result: Dict[str, Any] = {
        "bullet_changes": [],
        "tailored_summary": "",
        "summary": {"before": "", "after": "", "why": ""},
        "unchanged_targets": [],
        "guardrail_notes": ["Refinery export uses gap-guided bullet merges only; no posting rewrite."],
        "tailored_experience_bullets": [],
        "tailored_skills": [],
        "change_items": [],
    }
    return rewrite_result, score_result, mapping_result, job_signals
