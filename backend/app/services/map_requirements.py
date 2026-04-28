"""
Deterministic requirement-to-evidence mapping (no AI, no embeddings).

Every classification cites concrete evidence units from the resume.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.services.parse_job import (
    is_actionable_requirement_line,
    is_heading_like_line,
    is_marketing_or_manifesto_line,
    is_philosophy_like_line,
)
from app.utils.text_cleaning import normalize_whitespace

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

SECTION_WEIGHT_EXPERIENCE = 3.0
SECTION_WEIGHT_PROJECT = 2.5
SECTION_WEIGHT_SUMMARY = 1.5
SECTION_WEIGHT_SKILLS = 1.0
SECTION_WEIGHT_CERTIFICATION = 0.5
SECTION_WEIGHT_EDUCATION = 0.5
SECTION_WEIGHT_DEFAULT = 1.0

RECENCY_MOST_RECENT = 2
RECENCY_SECOND = 1
RECENCY_OLDER = 0
RECENCY_NON_EXPERIENCE = 0

STRONG_MATCH_SCORE = 10.0
WEAK_MATCH_SCORE = 5.0

MAX_MATCHED_EVIDENCE_PER_REQUIREMENT = 2
MAX_REWRITE_TARGETS = 8

# When True, map_requirements_to_resume includes diagnostic-only keys in its return dict.
DEBUG_MODE = False
# Dampen base section weight for legacy line-split evidence (avoid false confidence)
LEGACY_SECTION_WEIGHT_FACTOR = 0.75
# Keyword overlap counts for less outside role bullets (summary/skills/etc.)
KEYWORD_WEIGHT_NON_ROLE = 0.55

GENERIC_PHRASES: Tuple[str, ...] = (
    "worked on",
    "helped with",
    "involved in",
    "responsible for",
    "participated in",
    "assisted with",
    "supported",
    "contributed to",
)

# ---------------------------------------------------------------------------
# Synonym maps (canonical group id -> search phrases / stems)
# ---------------------------------------------------------------------------

VERB_GROUPS: Dict[str, Tuple[str, ...]] = {
    "build": ("build", "built", "develop", "developed", "create", "created", "design", "designed"),
    "analyze": (
        "analyze",
        "analyzed",
        "assess",
        "assessed",
        "evaluate",
        "evaluated",
        "validate",
        "validated",
    ),
    "collaborate": (
        "collaborate",
        "collaborated",
        "partner",
        "partnered",
        "work with",
        "worked with",
    ),
    "lead": ("lead", "led", "leading", "own", "owned", "drive", "drove", "manage", "managed"),
    "optimize": (
        "optimize",
        "optimized",
        "improve",
        "improved",
        "streamline",
        "streamlined",
    ),
}

TOOL_GROUPS: Dict[str, Tuple[str, ...]] = {
    "power bi": ("power bi", "powerbi", "pbi"),
    "sql": ("sql", "query", "queries", "querying", "t-sql", "tsql"),
    "excel": ("excel", "spreadsheet", "spreadsheets"),
    "tableau": ("tableau",),
    "python": ("python", "pandas", "numpy"),
    "dynamics": ("dynamics 365", "dynamics365", "dynamics crm", "microsoft dynamics"),
    "crm": ("crm", "salesforce", "case management", "case management system"),
}

# Domain / practice equivalents (req evidence and resume evidence share a group → extra match signal).
DOMAIN_EQUIV_GROUPS: Dict[str, Tuple[str, ...]] = {
    "testing_uat": (
        "uat",
        "user acceptance",
        "acceptance testing",
        "qa",
        "quality assurance",
        "test case",
        "test cases",
        "defect",
        "defects",
        "triage",
        "validation testing",
        "system testing",
        "regression",
    ),
    "reporting_bi": (
        "reporting",
        "dashboard",
        "dashboards",
        "business intelligence",
        "power bi",
        "tableau",
        "looker",
        "analytics",
        "kpi",
        "metrics report",
    ),
    "sql_data": (
        "sql",
        "data validation",
        "data quality",
        "etl",
        "t-sql",
        "reporting analysis",
    ),
    "healthcare_gov": (
        "medicaid",
        "medicare",
        "hipaa",
        "healthcare",
        "clinical",
        "patient",
        "health plan",
        "government health",
        "state agency",
        "cms",
        "managed care",
        "public health",
    ),
    "crm_ops": (
        "crm",
        "case management",
        "dynamics",
        "service desk",
        "ticketing",
        "jira",
    ),
    "ba_stakeholder": (
        "business analyst",
        "business analysis",
        "stakeholder",
        "stakeholders",
        "requirements",
        "user story",
        "user stories",
        "process",
        "cross-functional",
        "facilitate",
        "facilitation",
        "workshop",
    ),
}

_STOP = frozenset(
    """
    the a an and or for with from that this your our are was were been be being is it in to of as at by on if we you their will can may not no
    all any some such than then them they these those into about over after before under other also just more most very when what which while
    who how why work team role job using use used must have has had having do does did doing
    """.split()
)

# Extra noise for object-like tokens (JD boilerplate, not good object targets)
_OBJECT_STOP = frozenset(
    """
    experience years year ability abilities skills skill strong proven demonstrated excellent good great
    minimum preferred required including such various multiple deep solid variously typically generally
    ideally desired desirable responsibilities responsibility functions function role roles position
    positions opportunity opportunities client clients internal external senior junior level levels
    using based across within through including toward towards related relevant similar effective
    communication written verbal oral interpersonal organizational time management self motivated
    """.split()
)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", text.lower())


def _significant_tokens(text: str) -> Set[str]:
    return {t for t in _tokenize(text) if len(t) > 2 and t not in _STOP}


def _filter_object_tokens(tokens: Sequence[str]) -> List[str]:
    """Drop generic JD residue; keep longer, more specific targets."""
    out: List[str] = []
    for x in tokens:
        xl = x.strip().lower()
        if len(xl) < 5:
            continue
        if xl in _STOP or xl in _OBJECT_STOP:
            continue
        out.append(xl)
    return out[:12]


def _phrase_variant_present(phrase_lower: str, text_lower: str) -> bool:
    """Whole phrase as consecutive tokens (not a raw substring inside unrelated words)."""
    parts = phrase_lower.split()
    if len(parts) < 2:
        return phrase_lower in set(_tokenize(text_lower))
    pattern = r"\s+".join(re.escape(p) for p in parts)
    return bool(re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text_lower))


def _label_set_from_text(text_lower: str, groups: Dict[str, Tuple[str, ...]]) -> Set[str]:
    """
    Map group labels using phrase match for multi-word variants and token equality for single-token variants
    (avoids accidental hits inside unrelated words).
    """
    found: Set[str] = set()
    token_set = set(_tokenize(text_lower))
    for label, variants in groups.items():
        for v in variants:
            vl = v.strip().lower()
            if len(vl) < 2:
                continue
            if " " in vl:
                if _phrase_variant_present(vl, text_lower):
                    found.add(label)
                    break
            else:
                if vl in token_set:
                    found.add(label)
                    break
    return found


def _display_tool_verb_labels(labels: Sequence[str]) -> str:
    """Readable list for notes (short)."""
    out: List[str] = []
    for L in labels:
        if L == "power bi":
            out.append("Power BI")
        elif L in ("sql", "excel", "python"):
            out.append(L.upper())
        else:
            out.append(L.replace("-", " ").title())
    return ", ".join(out)


def _recency_bonus_for_evidence(section: str, recency_rank: int, legacy_fallback: bool = False) -> int:
    # Legacy line-split evidence: do not treat as confidently "most recent role"
    if legacy_fallback and section == "experience":
        return RECENCY_OLDER
    if section not in ("experience", "project"):
        return RECENCY_NON_EXPERIENCE
    if recency_rank <= 1:
        return RECENCY_MOST_RECENT
    if recency_rank == 2:
        return RECENCY_SECOND
    return RECENCY_OLDER


def _section_weight(section: str) -> float:
    return {
        "experience": SECTION_WEIGHT_EXPERIENCE,
        "project": SECTION_WEIGHT_PROJECT,
        "summary": SECTION_WEIGHT_SUMMARY,
        "skills": SECTION_WEIGHT_SKILLS,
        "certification": SECTION_WEIGHT_CERTIFICATION,
        "education": SECTION_WEIGHT_EDUCATION,
    }.get(section, SECTION_WEIGHT_DEFAULT)


# ---------------------------------------------------------------------------
# Resume → evidence units
# ---------------------------------------------------------------------------


def _flatten_sections_to_evidence(resume_data: dict) -> List[Dict[str, Any]]:
    """
    Build ordered evidence units from resume_data['sections'] when present,
    else derive from legacy raw/summary shape.
    """
    units: List[Dict[str, Any]] = []
    sections = resume_data.get("sections")
    raw_text = resume_data.get("raw_text") or ""

    if isinstance(sections, dict):
        # Summary sentences
        for i, block in enumerate(sections.get("summary") or []):
            text = str(block).strip()
            if len(text) < 3:
                continue
            for j, sent in enumerate(_split_sentences(text)):
                st = sent.strip()
                if len(st) < 8:
                    continue
                units.append(
                    {
                        "id": f"summary_{i}_{j}",
                        "section": "summary",
                        "text": st,
                        "company": None,
                        "title": None,
                        "recency_rank": 99,
                        "section_weight": _section_weight("summary"),
                    }
                )

        # Experience bullets (first job = most recent)
        exp_blocks = sections.get("experience") or []
        for exp_idx, block in enumerate(exp_blocks):
            if not isinstance(block, dict):
                continue
            recency_rank = exp_idx + 1
            company = (block.get("company") or "").strip() or None
            title = (block.get("title") or "").strip() or None
            for b_idx, bullet in enumerate(block.get("bullets") or []):
                bt = str(bullet).strip()
                if len(bt) < 6:
                    continue
                units.append(
                    {
                        "id": f"exp_{exp_idx + 1}_bullet_{b_idx + 1}",
                        "section": "experience",
                        "text": bt,
                        "company": company,
                        "title": title,
                        "recency_rank": recency_rank,
                        "section_weight": _section_weight("experience"),
                    }
                )

        # Projects
        proj_blocks = sections.get("projects") or []
        for pi, proj in enumerate(proj_blocks):
            if not isinstance(proj, dict):
                continue
            recency_rank = pi + 1
            name = (proj.get("name") or proj.get("title") or "").strip() or None
            for b_idx, bullet in enumerate(proj.get("bullets") or []):
                bt = str(bullet).strip()
                if len(bt) < 6:
                    continue
                units.append(
                    {
                        "id": f"proj_{pi + 1}_bullet_{b_idx + 1}",
                        "section": "project",
                        "text": bt,
                        "company": name,
                        "title": None,
                        "recency_rank": recency_rank,
                        "section_weight": _section_weight("project"),
                    }
                )

        # Skills — one unit per entry, lower weight
        skills = sections.get("skills") or []
        if isinstance(skills, list):
            for si, sk in enumerate(skills):
                st = str(sk).strip()
                if len(st) < 2:
                    continue
                units.append(
                    {
                        "id": f"skills_{si + 1}",
                        "section": "skills",
                        "text": st,
                        "company": None,
                        "title": None,
                        "recency_rank": 99,
                        "section_weight": _section_weight("skills"),
                    }
                )

        # Certifications
        certs = sections.get("certifications") or []
        if isinstance(certs, list):
            for ci, cert in enumerate(certs):
                ct = str(cert).strip()
                if len(ct) < 3:
                    continue
                units.append(
                    {
                        "id": f"cert_{ci + 1}",
                        "section": "certification",
                        "text": ct,
                        "company": None,
                        "title": None,
                        "recency_rank": 99,
                        "section_weight": _section_weight("certification"),
                    }
                )

        if units:
            return units

    # Legacy fallback: lines from raw_text / raw.body_text
    body = raw_text
    if not body:
        raw = resume_data.get("raw") or {}
        if isinstance(raw, dict):
            body = raw.get("body_text") or ""
    summary = (resume_data.get("summary") or "").strip()
    lines = [ln.strip() for ln in body.split("\n") if len(ln.strip()) > 6]
    if not lines and summary:
        lines = [summary]
    for i, ln in enumerate(lines[:40]):
        is_summary_line = bool(summary) and ln.strip() == summary.strip()
        if i == 0 and is_summary_line:
            sec = "summary"
            rk = 99
        else:
            sec = "experience"
            rk = 1
        units.append(
            {
                "id": f"legacy_line_{i + 1}",
                "section": sec,
                "text": ln,
                "company": None,
                "title": None,
                "recency_rank": rk,
                "section_weight": _section_weight(sec),
                "legacy_fallback": True,
            }
        )
    return units


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _resume_evidence_snippet(resume_data: dict, units: Sequence[Dict[str, Any]]) -> str:
    if resume_data.get("raw_text"):
        return normalize_whitespace(str(resume_data["raw_text"]))
    return normalize_whitespace(" ".join(u["text"] for u in units))


# ---------------------------------------------------------------------------
# Job signals → requirement objects
# ---------------------------------------------------------------------------


def _build_requirement_objects(job_signals: dict) -> List[Dict[str, Any]]:
    """Flatten validated requirements into structured requirement dicts (deterministic labels)."""
    role_focus_raw = list(job_signals.get("role_focus") or [])
    rf_token_set: Set[str] = set()
    for rf in role_focus_raw:
        rf_token_set.update(_significant_tokens(str(rf)))

    pairs: List[Tuple[str, str]] = []
    vr = job_signals.get("validated_requirements") or []
    vp = list(job_signals.get("validated_requirement_priorities") or [])
    if isinstance(vr, list) and vr and len(vp) != len(vr):
        vp = ["must_have"] * len(vr)

    if isinstance(vr, list) and vr:
        seen_pairs: Set[str] = set()
        for i, raw in enumerate(vr):
            t = str(raw).strip()
            if len(t) < 3:
                continue
            if not is_actionable_requirement_line(t):
                continue
            pri = str(vp[i] if i < len(vp) else "must_have")
            if pri not in ("must_have", "preferred"):
                pri = "must_have"
            key = re.sub(r"\s+", " ", t.lower())[:120]
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            pairs.append((t, pri))
    else:
        for priority, key in (("must_have", "must_have_requirements"), ("preferred", "preferred_requirements")):
            for text in job_signals.get(key) or []:
                t = str(text).strip()
                if len(t) < 3:
                    continue
                if not is_actionable_requirement_line(t):
                    continue
                pairs.append((t, priority))

    reqs: List[Dict[str, Any]] = []
    idx = 0
    for text, priority in pairs:
        idx += 1
        t = text
        tl = t.lower()
        kw_list = sorted(_significant_tokens(t))[:24]
        req_kw_set = set(kw_list)
        tool_labels = sorted(_label_set_from_text(tl, TOOL_GROUPS))
        verb_labels = sorted(_label_set_from_text(tl, VERB_GROUPS))
        domain_labels = sorted(_label_set_from_text(tl, DOMAIN_EQUIV_GROUPS))
        tool_variant_tokens: Set[str] = set()
        for variants in TOOL_GROUPS.values():
            for v in variants:
                tool_variant_tokens.update(_tokenize(v))
        obj_tokens = _filter_object_tokens(
            [x for x in kw_list if x not in tool_variant_tokens and len(x) > 2]
        )
        domain_terms = sorted(req_kw_set & rf_token_set)[:10]
        cat = "general"
        if tool_labels and not verb_labels:
            cat = "tool_heavy"
        elif verb_labels and not tool_labels:
            cat = "action_heavy"

        reqs.append(
            {
                "id": f"req_{idx:02d}",
                "text": t,
                "priority": priority,
                "keywords": kw_list,
                "tool_labels": tool_labels,
                "verb_labels": verb_labels,
                "domain_labels": domain_labels,
                "object_tokens": obj_tokens,
                "domain_terms": domain_terms,
                "category": cat,
            }
        )
    return reqs


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _substantive_overlap(bd: Dict[str, Any], section: str = "") -> bool:
    """
    True only when requirement and evidence share concrete signals (not section weight alone).
    Keyword overlap alone only counts toward a match in role/project bullets, not summary/skills/etc.
    """
    if not bd:
        return False
    if (bd.get("tool_match") or 0) > 0 or (bd.get("verb_match") or 0) > 0:
        return True
    if (bd.get("domain_equiv_match") or 0) > 0:
        return True
    if (bd.get("object_match") or 0) > 0 or (bd.get("domain_match") or 0) > 0:
        return True
    if (bd.get("keyword_overlap_req") or 0) > 0 and section in ("experience", "project"):
        return True
    return False


def _domain_match_from_terms(evidence_tokens: Set[str], domain_terms: Sequence[str]) -> int:
    """Count domain terms that appear as whole tokens in evidence."""
    n = 0
    for d in domain_terms:
        ds = str(d).strip().lower()
        if len(ds) < 2:
            continue
        if ds in evidence_tokens:
            n += 1
    return n


def _score_evidence_for_requirement(
    req: Dict[str, Any],
    ev: Dict[str, Any],
) -> Tuple[float, Dict[str, Any]]:
    """
    Score using overlap between requirement-side labels and evidence-side labels.
    Tool/verb points only when the same canonical labels appear on both sides.
    """
    ev_text = ev["text"]
    el = ev_text.lower()
    section = ev["section"]

    req_kw = set(req.get("keywords") or [])
    ev_sig = _significant_tokens(ev_text)
    keyword_overlap_req = len(req_kw & ev_sig)
    job_bonus = 0
    keyword_overlap_total = keyword_overlap_req

    kw_weight = (
        1.0 if section in ("experience", "project") else KEYWORD_WEIGHT_NON_ROLE
    )

    req_tools = set(req.get("tool_labels") or [])
    req_verbs = set(req.get("verb_labels") or [])
    req_domains = set(req.get("domain_labels") or [])
    ev_tools = _label_set_from_text(el, TOOL_GROUPS)
    ev_verbs = _label_set_from_text(el, VERB_GROUPS)
    ev_domains = _label_set_from_text(el, DOMAIN_EQUIV_GROUPS)

    matched_tools = sorted(req_tools & ev_tools)
    matched_verbs = sorted(req_verbs & ev_verbs)
    matched_domains = sorted(req_domains & ev_domains)
    tool_match = len(matched_tools)
    verb_match = len(matched_verbs)
    domain_equiv_match = len(matched_domains)

    ev_word_set = set(_tokenize(el))
    object_match = sum(1 for o in req.get("object_tokens") or [] if o in ev_word_set)

    domain_terms = list(req.get("domain_terms") or [])
    domain_match = _domain_match_from_terms(ev_word_set, domain_terms)

    base_sw = float(ev.get("section_weight", _section_weight(section)))
    if bool(ev.get("legacy_fallback")):
        base_sw *= LEGACY_SECTION_WEIGHT_FACTOR
    recency_rank = int(ev.get("recency_rank", 99))
    recency_bonus = _recency_bonus_for_evidence(
        section, recency_rank, bool(ev.get("legacy_fallback", False))
    )

    weighted = (
        float(keyword_overlap_total) * 2.0 * kw_weight
        + float(tool_match) * 4.0
        + float(verb_match) * 2.0
        + float(domain_equiv_match) * 3.5
        + float(object_match) * 3.0
        + float(domain_match) * 1.0
        + base_sw
        + float(recency_bonus)
    )

    breakdown = {
        "keyword_overlap": int(keyword_overlap_req),
        "keyword_overlap_req": int(keyword_overlap_req),
        "job_keyword_bonus": int(job_bonus),
        "tool_match": int(tool_match),
        "verb_match": int(verb_match),
        "domain_equiv_match": int(domain_equiv_match),
        "object_match": int(object_match),
        "domain_match": int(domain_match),
        "section_weight": int(round(base_sw)),
        "recency_bonus": int(recency_bonus),
        "matched_tool_labels": matched_tools,
        "matched_verb_labels": matched_verbs,
        "matched_domain_labels": matched_domains,
    }
    return float(weighted), breakdown


def _strong_grounding(bd: Dict[str, Any]) -> bool:
    """
    Strong classification requires grounded signals — not score alone or keywords alone.
    """
    tm = (bd.get("tool_match") or 0) > 0
    vm = int(bd.get("verb_match") or 0)
    om = int(bd.get("object_match") or 0)
    dm = int(bd.get("domain_match") or 0)
    de = int(bd.get("domain_equiv_match") or 0)
    kw = int(bd.get("keyword_overlap_req") or bd.get("keyword_overlap") or 0)
    if tm:
        return True
    # Practice-area match on both sides plus any shared substantive token is a clear signal.
    if de >= 1 and kw >= 1:
        return True
    if de >= 1 and (tm or vm >= 1 or kw >= 2 or om >= 1):
        return True
    if vm >= 1 and om >= 1:
        return True
    if om >= 1 and dm >= 1:
        return True
    if om >= 2 and vm >= 1:
        return True
    return False


def _classify_requirement(
    score: float,
    best_ev: Optional[Dict[str, Any]],
    bd: Dict[str, Any],
) -> str:
    """Return strong | weak | missing."""
    if not best_ev or score < WEAK_MATCH_SCORE:
        return "missing"

    section = best_ev.get("section", "")

    # Skills-only: should not yield strong; cap at weak
    if section == "skills":
        if score >= WEAK_MATCH_SCORE:
            return "weak"
        return "missing"

    if section in ("experience", "project"):
        if score >= STRONG_MATCH_SCORE:
            if _strong_grounding(bd):
                return "strong"
            return "weak"
        if score >= WEAK_MATCH_SCORE:
            return "weak"
        return "missing"

    # Summary / cert / education — never strong
    if score >= WEAK_MATCH_SCORE:
        return "weak"
    return "missing"


def _note_for_match(
    classification: str,
    section: str,
    bd: Dict[str, Any],
) -> str:
    if classification == "missing":
        return "No direct requirement-specific evidence was found."
    mt: List[str] = list(bd.get("matched_tool_labels") or [])
    mv: List[str] = list(bd.get("matched_verb_labels") or [])
    md: List[str] = list(bd.get("matched_domain_labels") or [])
    kw_req = int(bd.get("keyword_overlap_req") or 0)
    om = int(bd.get("object_match") or 0)
    dm = int(bd.get("domain_match") or 0)
    skills_only = section == "skills"

    if classification == "strong":
        if md and not mt and not mv:
            pretty = ", ".join(m.replace("_", " ") for m in md[:3])
            return f"Aligned practice areas ({pretty}) show up for this need in recent experience."
        if mt and mv:
            return f"Clear overlap on tools ({_display_tool_verb_labels(mt)}) and actions ({_display_tool_verb_labels(mv)}) in recent experience."
        if mt:
            return f"Concrete use of {_display_tool_verb_labels(mt)} shows up in recent experience."
        if mv:
            return f"Action language ({_display_tool_verb_labels(mv)}) matches this need in recent experience."
        if om and dm:
            return "Themes and domain wording both line up in recent experience."
        if om >= 2:
            return "Several concrete themes from the need appear in recent experience."
        if dm:
            return "Domain wording lines up in recent experience; tools and actions are less explicit."
        return "Shows a clear fit in recent experience for this need."

    if classification == "weak":
        if skills_only:
            return "Support appears mostly in the skills section rather than recent role bullets."
        if mt or mv:
            return f"Touches {_display_tool_verb_labels(mt + mv)}, but the connection to this need is still loose."
        if om or dm:
            if section == "summary":
                return "Themes echo at a high level; concrete role-level ownership is not yet clear."
            if section in ("certification", "education"):
                return "Themes echo here; depth in a recent role is not yet clear."
            return "Themes line up indirectly; ownership or depth is not yet clear in the experience bullets."
        if kw_req:
            return "Shared wording only — the fit to this need is indirect."
        return "Partial fit; evidence is thin or high-level for this need."

    return "No direct requirement-specific evidence was found."


def _gap_line_for_requirement(req_text: str) -> str:
    """Short, human-readable gap line (neutral tone)."""
    t = req_text.strip()
    t = re.sub(r"^[\s\-•*]+", "", t)
    t = re.sub(
        r"^(must|should|required to|ability to|experience with|demonstrated|proven|proficiency in)\s+",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^the\s+", "", t, flags=re.I)
    if len(t) > 70:
        cut = t[:70]
        if "," in cut:
            t = cut[: cut.rfind(",")].strip()
        else:
            t = cut.rstrip() + "…"
    if not t:
        return "Direct evidence for this need is not clearly shown."
    theme = t[0].lower() + t[1:] if len(t) > 1 else t.lower()
    return f"Direct {theme} is not clearly shown."


_FLAT_OPENING = re.compile(
    r"^(worked|helped|assisted|supported|involved|participated)\b",
    re.I,
)


def _is_flat_or_weak_opening(text: str) -> bool:
    return bool(_FLAT_OPENING.search(text.strip()))


def _is_generic_wording(text: str) -> bool:
    tl = text.lower()
    return any(gp in tl for gp in GENERIC_PHRASES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def map_requirements_to_resume(resume_data: dict, job_signals: dict) -> dict:
    """
    Map each job requirement to the best resume evidence with deterministic scoring.

    Returns (product payload):
        requirement_matches, rewrite_targets, gaps.

    When DEBUG_MODE is True, also includes resume_evidence_snippet and evidence_by_requirement.
    """
    units = _flatten_sections_to_evidence(resume_data)
    snippet = ""
    if DEBUG_MODE:
        snippet = _resume_evidence_snippet(resume_data, units).lower()

    requirements = _build_requirement_objects(job_signals)
    # Canonical list for all downstream recruiter output (overwrites extract-time list with same filtered objects).
    job_signals["validated_requirements"] = [r["text"] for r in requirements]
    job_signals["validated_requirement_priorities"] = [str(r.get("priority") or "must_have") for r in requirements]
    job_signals["must_have_requirements"] = [
        r["text"] for r in requirements if r.get("priority") == "must_have"
    ][:10]
    job_signals["preferred_requirements"] = [
        r["text"] for r in requirements if r.get("priority") == "preferred"
    ][:10]

    requirement_results: List[Dict[str, Any]] = []
    evidence_by_req: Dict[str, str] = {}

    for req in requirements:
        scored: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
        for ev in units:
            total, bd = _score_evidence_for_requirement(req, ev)
            scored.append((total, ev, bd))
        scored.sort(key=lambda x: -x[0])

        if not scored:
            best_score, best_ev, best_bd = 0.0, None, {}
        else:
            best_score, best_ev, best_bd = scored[0]

        classification = _classify_requirement(best_score, best_ev, best_bd)
        if best_ev is None:
            classification = "missing"
        elif not _substantive_overlap(
            best_bd, str(best_ev.get("section", "") if best_ev else "")
        ):
            classification = "missing"

        out_bd = dict(best_bd) if best_ev else {}
        display_score = round(best_score, 2)
        if classification == "missing":
            display_score = round(min(best_score, WEAK_MATCH_SCORE - 0.01), 2)

        matched_evidence: List[Dict[str, Any]] = []
        if classification != "missing":
            for _, ev, _ in scored[:MAX_MATCHED_EVIDENCE_PER_REQUIREMENT]:
                matched_evidence.append(
                    {
                        "id": ev["id"],
                        "section": ev["section"],
                        "company": ev.get("company"),
                        "title": ev.get("title"),
                        "text": ev["text"],
                    }
                )

        if DEBUG_MODE and classification != "missing" and best_ev:
            evidence_by_req[req["text"]] = best_ev["text"]

        notes = _note_for_match(
            classification,
            best_ev.get("section", "") if best_ev else "",
            out_bd,
        )

        requirement_results.append(
            {
                "requirement_id": req["id"],
                "requirement_text": req["text"],
                "priority": req["priority"],
                "classification": classification,
                "score": display_score,
                "matched_evidence": matched_evidence,
                "score_breakdown": out_bd if classification != "missing" else {},
                "notes": notes,
            }
        )

    gaps: List[str] = []
    for row in requirement_results:
        if row["classification"] == "missing":
            rt = str(row.get("requirement_text") or "")
            if (
                is_philosophy_like_line(rt)
                or is_heading_like_line(rt)
                or is_marketing_or_manifesto_line(rt)
            ):
                continue
            gaps.append(_gap_line_for_requirement(rt))

    meta = resume_data.get("meta") if isinstance(resume_data.get("meta"), dict) else {}
    if not bool(meta.get("parse_ok", True)):
        gaps.append("Resume text could not be fully parsed; evidence matching may be incomplete.")

    ev_must_counts: Dict[str, int] = defaultdict(int)
    for row in requirement_results:
        if row["priority"] != "must_have":
            continue
        if row["classification"] == "missing":
            continue
        for evd in row.get("matched_evidence") or []:
            eid = evd.get("id")
            if eid:
                ev_must_counts[str(eid)] += 1

    seen_ids: Set[str] = set()
    rewrite_targets: List[Dict[str, Any]] = []
    for row in requirement_results:
        if row["priority"] != "must_have":
            continue
        if row["classification"] not in ("strong", "weak"):
            continue
        for evd in row.get("matched_evidence") or []:
            if evd.get("section") != "experience":
                continue
            eid = evd.get("id")
            if not eid:
                continue
            eid_s = str(eid)
            if eid_s in seen_ids:
                continue
            txt = (evd.get("text") or "").strip()
            if not txt:
                continue
            multi = ev_must_counts.get(eid_s, 0) >= 2
            generic = _is_generic_wording(txt)
            flat = _is_flat_or_weak_opening(txt)
            if not (generic or flat or multi):
                continue
            seen_ids.add(eid_s)
            if multi:
                reason = "Multiple must-have themes touch this bullet; tighten wording for clearer impact."
            else:
                reason = "Relevant evidence uses generic phrasing; can better reflect role-specific alignment."
            rewrite_targets.append(
                {
                    "evidence_id": eid_s,
                    "section": "experience",
                    "company": evd.get("company"),
                    "text": txt,
                    "reason": reason,
                }
            )
            if len(rewrite_targets) >= MAX_REWRITE_TARGETS:
                break
        if len(rewrite_targets) >= MAX_REWRITE_TARGETS:
            break

    if len(rewrite_targets) < 3 and units:
        for ev in units:
            if ev["section"] != "experience":
                continue
            eid_s = str(ev["id"])
            if eid_s in seen_ids:
                continue
            txt = (ev.get("text") or "").strip()
            multi = ev_must_counts.get(eid_s, 0) >= 2
            if not multi and not _is_generic_wording(txt) and not _is_flat_or_weak_opening(txt):
                continue
            seen_ids.add(eid_s)
            reason = (
                "Multiple must-have themes touch this bullet; tighten wording for clearer impact."
                if multi
                else "Generic phrasing; can foreground stronger alignment with stated needs."
            )
            rewrite_targets.append(
                {
                    "evidence_id": eid_s,
                    "section": "experience",
                    "company": ev.get("company"),
                    "text": txt,
                    "reason": reason,
                }
            )
            if len(rewrite_targets) >= MAX_REWRITE_TARGETS:
                break

    payload: Dict[str, Any] = {
        "requirement_matches": requirement_results,
        "rewrite_targets": rewrite_targets,
        "gaps": gaps[:20],
    }
    if DEBUG_MODE:
        payload["resume_evidence_snippet"] = snippet
        payload["evidence_by_requirement"] = evidence_by_req
    return payload
