"""
Builds Tailor response payloads, including preview text, fit notes, and change-review metadata.

``tailored_resume_text`` is a skim preview (summary plus a few top bullets), not a full resume.
Use ``prioritized_bullet_changes`` for experience edits; ``change_breakdown`` is secondary (summary wording only, for older clients).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.parse_job import (
    is_actionable_requirement_line,
    is_benefits_line,
    is_company_about_line,
    is_employment_meta_line,
    is_generic_responsibility_line,
    is_heading_like_line,
    is_manifesto_or_values_line,
    is_marketing_or_manifesto_line,
    is_philosophy_like_line,
    requirement_allowed_in_pipeline,
)
from app.services.resume_presentation import is_tool_centric_summary
from app.services.rewrite_resume import (
    _corpus_from_resume,
    _current_summary_text,
    _enforce_summary_resume_only,
    _resume_grounded_poor_fit_summary,
    _strip_bad_summary_phrases,
    _summary_input_has_jd_pollution,
    _trim_redundant_words,
)

logger = logging.getLogger(__name__)

_PARSE_GAP_HINT = "could not be fully parsed"

_TAILOR_WEAK_MINIMAL_LEXICON = re.compile(
    r"(?i)^professional\s+with\s+experience\s+in\s+analysis,\s+delivery,\s+and\s+documentation\s+in\s+professional\s+settings\.?$"
)

def is_weak_tailor_summary(summary: str) -> bool:
    """
    True when a Tailor-generated summary is too generic / tool-listy to prefer over a
    stronger resume summary (response-path gate only — not export validation).
    """
    s = (summary or "").strip()
    if not s:
        return True
    low = s.lower()
    # Catches ``… in excel…`` and enforce-template lines like ``… applying sql…``.
    if re.match(r"(?i)^professional\s+with\s+experience\b", s):
        return True
    if "excel, power bi, and python" in low:
        return True
    if is_tool_centric_summary(s):
        return True
    if _TAILOR_WEAK_MINIMAL_LEXICON.match(re.sub(r"\s+", " ", s).strip()):
        return True
    return False

_SAFE_SKIM_LINES = frozenset(
    {
        "No strong standout signal surfaced for this posting.",
    }
)

# Recruiter-facing strings: “…” or straight quotes around echoed requirement snippets
_QUOTED_FRAG = re.compile(r"[\u201c\"]([^\u201d\"]{4,})[\u201d\"]")


def _quoted_fragments(s: str) -> List[str]:
    return [m.group(1).strip() for m in _QUOTED_FRAG.finditer(s or "")]


def _recruiter_line_banned_full(s: str) -> bool:
    """Unquoted recruiter line: drop manifesto, about, generic responsibility, benefits."""
    t = (s or "").strip()
    if not t:
        return True
    if is_philosophy_like_line(t) or is_marketing_or_manifesto_line(t):
        return True
    if is_manifesto_or_values_line(t) or is_company_about_line(t) or is_benefits_line(t):
        return True
    if is_employment_meta_line(t):
        return True
    if is_generic_responsibility_line(t):
        return True
    return False


def _defensive_drop_quoted_junk(line: str, job_signals: Optional[dict]) -> bool:
    """True = drop line: a quoted snippet fails validated pipeline or banned JD copy."""
    for frag in _quoted_fragments(line):
        if len(frag) < 12:
            continue
        if not requirement_allowed_in_pipeline(frag, job_signals):
            return True
        low = frag.strip()
        if (
            is_generic_responsibility_line(low)
            or is_manifesto_or_values_line(low)
            or is_company_about_line(low)
            or is_benefits_line(low)
        ):
            return True
    return False


def _defensive_filter_string_list(
    lines: List[str], job_signals: Optional[dict]
) -> List[str]:
    out: List[str] = []
    for ln in lines or []:
        s = str(ln or "").strip()
        if not s:
            continue
        if s in _SAFE_SKIM_LINES:
            out.append(s)
            continue
        if _recruiter_line_banned_full(s):
            continue
        if _defensive_drop_quoted_junk(s, job_signals):
            continue
        out.append(s)
    return out


def _defensive_filter_why_matches(
    items: List[Dict[str, str]], job_signals: Optional[dict]
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        req = str(it.get("requirement") or "").strip()
        if not req or not requirement_allowed_in_pipeline(req, job_signals):
            continue
        why = str(it.get("why") or "")
        if why.strip() and (
            _recruiter_line_banned_full(why) or _defensive_drop_quoted_junk(why, job_signals)
        ):
            continue
        out.append(it)
    return out


def _finalize_recruiter_requirement_output(
    top_alignment_highlights: List[str],
    top_gaps_to_watch: List[str],
    why_this_matches: List[Dict[str, str]],
    gap_analysis: List[str],
    job_signals: Optional[dict],
) -> Tuple[List[str], List[str], List[Dict[str, str]], List[str]]:
    """Last-line filter: nothing that echoes non-validated or banned requirement copy."""
    return (
        _defensive_filter_string_list(top_alignment_highlights, job_signals),
        _defensive_filter_string_list(top_gaps_to_watch, job_signals),
        _defensive_filter_why_matches(why_this_matches, job_signals),
        _defensive_filter_string_list(gap_analysis, job_signals),
    )


def _sanitize_bullet_change_row(
    row: Dict[str, Any], job_signals: Optional[dict]
) -> Dict[str, Any]:
    """Strip JD/manifesto echo from bullet why / notes / suggestions (LLM or coaching)."""
    r = dict(row)
    for key in ("why", "recruiter_note"):
        v = str(r.get(key) or "").strip()
        if v and (
            _recruiter_line_banned_full(v) or _defensive_drop_quoted_junk(v, job_signals)
        ):
            r[key] = (
                "Wording stays tied to your resume; no posting-only lines."
                if key == "why"
                else "Readable at a glance; same facts as your resume."
            )
    raw_sug = r.get("suggestions")
    if isinstance(raw_sug, list):
        clean: List[str] = []
        for s in raw_sug:
            t = str(s).strip()
            if not t:
                continue
            if _recruiter_line_banned_full(t) or _defensive_drop_quoted_junk(t, job_signals):
                continue
            clean.append(t)
        r["suggestions"] = clean[:5]
    return r


def _requirement_text_is_non_fit_junk(text: str) -> bool:
    """Benefits, about copy, values, etc. must not drive highlights, gaps, or fit rows."""
    t = (text or "").strip()
    if not t:
        return True
    return not is_actionable_requirement_line(t)

_WORD_TOK = re.compile(r"[a-zA-Z']+")
_VERB_HINT = re.compile(
    r"\b(?:is|are|was|were|be|been|have|has|had|do|does|did|will|would|could|should|may|might|can|must|"
    r"work|lead|manage|build|create|develop|design|support|analyze|implement|deliver|drive|show|shows|shown|"
    r"demonstrate|include|includes|require|requires|need|needs|use|uses|using|make|makes|made)\b",
    re.I,
)
_HEADING_HINT = re.compile(
    r"^(employment\s+type|job\s+type|job\s+category|location|salary(?:\s+range)?|remote|hybrid|on[- ]?site|"
    r"about\s+the\s+(role|company|position)|about\s+(us|the\s+team|our\s+story)|company\s+overview|overview|who\s+we\s+are|why\s+join|"
    r"qualifications?|requirements?|responsibilities?|benefits?|perks?|culture|values)$",
    re.I,
)
_PHILOSOPHY_OR_BRAND = re.compile(
    r"\b("
    r"values|mission|vision|passion|purpose-driven|inclusion|diversity|equity|"
    r"we believe|why we|life at|join our|our story|brand promise|philosophy|"
    r"innovation culture|fast-paced|collaborative environment"
    r")\b",
    re.I,
)
_SLOGAN_LIKE = re.compile(r'["“].{12,}["”]')


def _word_count(s: str) -> int:
    return len(_WORD_TOK.findall(s or ""))


def _has_verb_hint(s: str) -> bool:
    return _VERB_HINT.search(s or "") is not None


def _looks_like_company_or_label(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return True
    if re.search(r"\b(inc\.?|llc\.?|ltd\.?|corp\.?|corporation|plc)\b", t, re.I):
        return True
    if _word_count(t) <= 3 and not _has_verb_hint(t) and t[0:1].isupper():
        return True
    return False


def _gap_has_action_signal(text: str) -> bool:
    """True if line plausibly names a skill, tool, scope, or responsibility."""
    tl = (text or "").lower()
    if _VERB_HINT.search(tl):
        return True
    if re.search(
        r"\b(sql|python|azure|aws|salesforce|dynamics|jira|tableau|power bi|excel|agile|scrum|"
        r"uat|qa|defect|stakeholder|medicaid|hipaa|crm|reporting|dashboard|etl|api|"
        r"certification|degree|years?|lead|manage|own|deliver|build|analyze)\b",
        tl,
    ):
        return True
    return False


def _is_non_actionable_gap_text(text: str) -> bool:
    """Drop philosophy, employer marketing, slogans, and narrative blobs."""
    t = (text or "").strip()
    if not t:
        return True
    if is_heading_like_line(t) or is_philosophy_like_line(t) or is_marketing_or_manifesto_line(t):
        return True
    if _PHILOSOPHY_OR_BRAND.search(t):
        return True
    if _word_count(t) > 42:
        return True
    if t.count('"') >= 4 or _SLOGAN_LIKE.search(t):
        return True
    if t.count("—") >= 3 and _word_count(t) > 20:
        return True
    if not _gap_has_action_signal(t) and _word_count(t) > 14:
        return True
    return False


def _is_noise_gap_source(text: str) -> bool:
    """Heading-like, too-short, or non-actionable fragment."""
    t = (text or "").strip()
    if not t:
        return True
    if _is_non_actionable_gap_text(t):
        return True
    first = t.split(".")[0].strip()
    # Employer “About …” blurbs, not role requirements
    if re.match(r"^about\s+", first.strip(), re.I) and _word_count(t) < 24:
        return True
    if _HEADING_HINT.match(first.strip()):
        return True
    if _word_count(t) < 4 and not _has_verb_hint(t):
        return True
    if _looks_like_company_or_label(t) and _word_count(t) < 10:
        return True
    return False


def _noise_to_actionable_gap(req_text: str, priority: str, variant: int) -> str:
    """Turn noisy requirement labels into a readable, actionable line."""
    low = (req_text or "").lower().strip()
    if "employment" in low and "type" in low:
        return (
            "How your employment or contract preferences align with this role is not stated on the resume."
        )
    if low.startswith("about ") and len(low) < 48:
        return "Narrative or employer background from the posting is not mirrored with your own evidence here."
    if _looks_like_company_or_label(req_text or ""):
        return "No clear example tied to that employer or label is shown in your lines—expand with your own facts if relevant."
    return _decision_gap_line("stated role expectations", priority, variant)


# ---------------------------------------------------------------------------


def _shorten(text: str, max_len: int = 72) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_len:
        return t
    cut = t[: max_len - 1].rsplit(" ", 1)[0]
    return (cut or t[: max_len]).rstrip() + "…"


def _req_fingerprint(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").lower()).strip()
    return t[:48]


def _requirement_row_allowed_for_output(req_text: str, job_signals: Optional[dict]) -> bool:
    """Single gate: actionable requirement + membership in validated_requirements when present."""
    return requirement_allowed_in_pipeline(str(req_text or ""), job_signals)


def _sorted_matched_evidence(row: dict) -> List[dict]:
    evs = [e for e in (row.get("matched_evidence") or []) if isinstance(e, dict)]
    if not evs:
        return []

    def sort_key(ev: dict) -> Tuple[int, int, int]:
        sec = str(ev.get("section") or "")
        sec_pri = 0 if sec == "experience" else (1 if sec == "project" else 2)
        em, eb = _parse_exp_bullet_id(str(ev.get("id") or ""))
        return (sec_pri, em, eb)

    return sorted(evs, key=sort_key)


def _first_evidence_text(row: dict) -> str:
    for ev in _sorted_matched_evidence(row):
        if (ev.get("text") or "").strip():
            return _shorten(str(ev["text"]), 220)
    return ""


def _sounds_debuggy(notes: str) -> bool:
    n = (notes or "").lower()
    return any(
        x in n
        for x in (
            "score_breakdown",
            "classification",
            "req_",
            "evidence_id",
            "mapper",
            "keyword_overlap",
            "validated against",
            "llm output",
            "deterministic edit",
            "summary rewrite rejected",
        )
    )


def _highlight_row_sort_key(row: dict) -> Tuple[float, int, int, int, float]:
    pri = str(row.get("priority") or "")
    pri_w = 2 if pri == "must_have" else (1 if pri == "preferred" else 0)
    sc = float(row.get("score") or 0.0)
    exp_em = 999
    has_exp = 0
    for ev in _sorted_matched_evidence(row):
        if str(ev.get("section") or "") == "experience":
            has_exp = 1
            em, _ = _parse_exp_bullet_id(str(ev.get("id") or ""))
            exp_em = min(exp_em, em)
            break
    return (pri_w, has_exp, -exp_em, sc)


def _alignment_label(row: dict) -> str:
    """UI-facing fit label (no backend jargon)."""
    return "clear" if row.get("classification") == "strong" else "partial"


def _public_match_why(row: dict, job_signals: Optional[dict] = None) -> str:
    notes = str(row.get("notes") or "").strip()
    if notes and not _sounds_debuggy(notes):
        if not (
            _recruiter_line_banned_full(notes) or _defensive_drop_quoted_junk(notes, job_signals)
        ):
            return _shorten(notes, 200)
    req = _shorten(str(row.get("requirement_text") or ""), 64)
    v = sum(ord(c) for c in req[:120]) % 3
    if row.get("classification") == "strong":
        opts = (
            f"Clear overlap with “{req}” in what is on the page.",
            f"Specific wording supports “{req}.”",
            f"Enough detail on “{req}” to assess fit.",
        )
        return opts[v]
    if row.get("classification") == "weak":
        opts = (
            f"Partial overlap with “{req}”; thin on detail.",
            f"“{req}” is only hinted at in the bullets.",
            f"Light touch on “{req}”; not the main thread.",
        )
        return opts[v]
    return f"Nothing solid on “{req}” in the text provided."


def _highlight_from_row(row: dict, variant: int) -> str:
    """One sentence, observation-style; grounded in matched lines only."""
    req = _shorten(str(row.get("requirement_text") or ""), 44)
    evs = _sorted_matched_evidence(row)
    ev_text = ""
    if evs and (evs[0].get("text") or "").strip():
        ev_text = _shorten(str(evs[0]["text"]), 72)
    in_exp = any(str(e.get("section") or "") == "experience" for e in evs)
    where = "the latest role" if in_exp else "the resume"

    if ev_text:
        seeds = (
            f"{ev_text} — ties to “{req}” ({where}).",
            f"{where.capitalize()}: wording on “{req}” includes {ev_text}",
            f"Visible line on “{req}”: {ev_text}",
        )
        line = seeds[variant % len(seeds)].rstrip()
        if not line.endswith("."):
            line += "."
        return _shorten(line, 155)

    return _shorten(f"Language on “{req}” appears in {where}.", 140)


def _gather_top_alignment_highlights(
    mapping_result: dict, limit: int = 3, job_signals: Optional[dict] = None
) -> List[str]:
    rows = [
        r
        for r in (mapping_result.get("requirement_matches") or [])
        if isinstance(r, dict) and r.get("classification") == "strong"
    ]
    rows.sort(key=_highlight_row_sort_key, reverse=True)
    out: List[str] = []
    seen_fp: set = set()
    i = 0
    for row in rows:
        if len(out) >= limit:
            break
        rtxt = str(row.get("requirement_text") or "")
        if not _requirement_row_allowed_for_output(rtxt, job_signals):
            continue
        if _requirement_text_is_non_fit_junk(rtxt):
            continue
        fp = _req_fingerprint(rtxt)
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        out.append(_highlight_from_row(row, i))
        i += 1
    if not out:
        return ["No strong standout signal surfaced for this posting."]
    return out


def _is_parse_meta_gap(line: str) -> bool:
    return _PARSE_GAP_HINT in (line or "").lower()


def _decision_gap_line(requirement_text: str, priority: str, variant: int) -> str:
    """Decision-oriented; vary sentence shape to reduce repetition."""
    t = _shorten(str(requirement_text), 68)
    v = variant % 3
    if priority == "must_have":
        opts = (
            f"Ownership of “{t}” is not clearly demonstrated in current resume bullets.",
            f"Does not clearly demonstrate “{t}.”",
            f"“{t}” lacks a clear, stand-alone example.",
        )
        return opts[v]
    if priority == "preferred":
        opts = (
            f"Limited visible evidence of “{t}.”",
            f"“{t}” is thinly supported at best.",
            f"Hard to verify “{t}” from what is on the page.",
        )
        return opts[v]
    opts = (
        f"“{t}” is not clearly shown.",
        f"No firm read on “{t}.”",
        f"Unclear how “{t}” shows up in practice.",
    )
    return opts[v]


def _gather_top_gaps_to_watch(
    mapping_result: dict, limit: int = 3, job_signals: Optional[dict] = None
) -> List[str]:
    return _normalized_gap_list(mapping_result, limit, job_signals)


def _soften_legacy_gap_line(line: str, variant: int) -> str:
    m = re.match(r"^Direct (.+) is not clearly shown\.\s*$", line.strip(), re.I)
    if m:
        theme = m.group(1).strip()
        return _decision_gap_line(theme, "general", variant)
    return line


def _normalize_gap_phrasing(line: str) -> str:
    s = (line or "").strip()
    if not s.endswith("."):
        s += "."
    return s


def _normalize_gap_actionable(requirement_text: str, priority: str, variant: int) -> str:
    """Prefer actionable phrasing for short or heading-like requirements."""
    t = (requirement_text or "").strip()
    if _word_count(t) >= 4 and _has_verb_hint(t):
        return _decision_gap_line(t, priority, variant)
    short = _shorten(t, 64)
    v = variant % 3
    if priority == "must_have" and v == 2:
        return f"Leadership or ownership for {short} is not clearly demonstrated."
    if v == 0:
        return f"No clear example of {short} is shown."
    return f"Experience with {short} is not clearly evidenced."


def _normalized_gap_list(
    mapping_result: dict, limit: int = 3, job_signals: Optional[dict] = None
) -> List[str]:
    """Actionable gaps only; deduped; max 3."""
    cap = min(max(limit, 1), 3)
    ranked: List[Tuple[int, str, str]] = []
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict) or row.get("classification") != "missing":
            continue
        rt = str(row.get("requirement_text") or "").strip()
        if not rt or not _requirement_row_allowed_for_output(rt, job_signals):
            continue
        pri = str(row.get("priority") or "")
        weight = 2 if pri == "must_have" else (1 if pri == "preferred" else 0)
        ranked.append((weight, rt, pri))
    ranked.sort(key=lambda x: -x[0])
    seen: set = set()
    ordered: List[str] = []
    prefixes: List[str] = []
    var_i = 0

    def near_dup(ln: str) -> bool:
        pfx = ln[:40].lower()
        if pfx in prefixes:
            return True
        for o in ordered:
            if ln.lower() in o.lower() or o.lower() in ln.lower():
                if min(len(ln), len(o)) > 24:
                    return True
        prefixes.append(pfx)
        return False

    for _, rt, pri in ranked:
        if not _requirement_row_allowed_for_output(rt, job_signals):
            continue
        if _requirement_text_is_non_fit_junk(rt):
            continue
        if _is_non_actionable_gap_text(rt):
            continue
        if _is_noise_gap_source(rt):
            ln = _noise_to_actionable_gap(rt, pri, var_i)
        else:
            ln = _normalize_gap_actionable(rt, pri, var_i)
        var_i += 1
        ln = _normalize_gap_phrasing(ln)
        if not ln or ln.lower() in seen or near_dup(ln):
            continue
        seen.add(ln.lower())
        ordered.append(ln)
        if len(ordered) >= cap:
            return ordered[:cap]

    # Do not consume mapping_result["gaps"] strings here: they are preformatted and are not
    # fingerprint-equal to validated_requirements; missing rows above are the single source.

    for g in mapping_result.get("gaps") or []:
        ln = str(g).strip()
        if _is_parse_meta_gap(ln) and ln.lower() not in seen and len(ordered) < cap:
            ordered.append("Some resume lines may not have been captured fully.")
            break

    return ordered[:cap]


def _format_gap_analysis_lines(mapping_result: dict, job_signals: Optional[dict] = None) -> List[str]:
    """Aligned with top gaps: actionable, deduped, capped."""
    return list(_normalized_gap_list(mapping_result, 3, job_signals))


def _parse_exp_bullet_id(eid: str) -> Tuple[int, int]:
    m = re.match(r"^exp_(\d+)_bullet_(\d+)$", (eid or "").strip())
    if not m:
        return (999, 999)
    return (int(m.group(1)), int(m.group(2)))


def _touches_for_evidence(
    eid: str, mapping_result: dict, job_signals: Optional[dict] = None
) -> Tuple[int, int, int]:
    """must_have hits, strong hits, weak hits (for deprioritizing weak-only bullets)."""
    must_n = 0
    strong_n = 0
    weak_n = 0
    for row in mapping_result.get("requirement_matches") or []:
        if not isinstance(row, dict):
            continue
        rt = str(row.get("requirement_text") or "").strip()
        if not requirement_allowed_in_pipeline(rt, job_signals):
            continue
        if row.get("classification") == "missing":
            continue
        hit = False
        for ev in row.get("matched_evidence") or []:
            if isinstance(ev, dict) and str(ev.get("id") or "") == eid:
                hit = True
                break
        if not hit:
            continue
        if str(row.get("priority") or "") == "must_have":
            must_n += 1
        if row.get("classification") == "strong":
            strong_n += 1
        elif row.get("classification") == "weak":
            weak_n += 1
    return (must_n, strong_n, weak_n)


def _clarity_delta_words(before: str, after: str) -> int:
    return len(str(after).split()) - len(str(before).split())


def _prioritize_bullet_changes(
    rewrite_result: dict, mapping_result: dict, job_signals: Optional[dict] = None
) -> List[Dict[str, Any]]:
    raw = rewrite_result.get("bullet_changes") or []
    if not isinstance(raw, list):
        return []

    enriched: List[Tuple[Tuple[int, int, int, int, int, int, int, int, int], Dict[str, Any]]] = []
    for bc in raw:
        if not isinstance(bc, dict):
            continue
        eid = str(bc.get("evidence_id") or "")
        must_t, strong_t, weak_t = _touches_for_evidence(eid, mapping_result, job_signals)
        em, eb = _parse_exp_bullet_id(eid)
        clarity = _clarity_delta_words(str(bc.get("before") or ""), str(bc.get("after") or ""))
        mode = str(bc.get("mode") or "").strip()
        if not mode:
            material_txt = str(bc.get("before") or "").strip() != str(bc.get("after") or "").strip()
            mode = "rewrite" if material_txt else "unchanged"
        material = 1 if mode == "rewrite" else 0
        raw_sug = bc.get("suggestions")
        suggestions = raw_sug if isinstance(raw_sug, list) else []
        suggestions = [str(s).strip() for s in suggestions if str(s).strip()][:5]
        weak_only = 1 if must_t == 0 and strong_t == 0 and weak_t > 0 else 0
        deprioritize_unchanged_strong = 1 if material == 0 and strong_t >= 1 else 0
        quiet = 1 if mode == "unchanged" else 0
        key = (
            1 - weak_only,
            must_t,
            strong_t,
            -weak_t,
            material,
            -deprioritize_unchanged_strong,
            -quiet,
            -em,
            -eb,
            abs(clarity),
        )
        enriched.append((key, bc))

    enriched.sort(key=lambda x: x[0], reverse=True)

    n = len(enriched)
    out: List[Dict[str, Any]] = []
    for rank, (_, bc) in enumerate(enriched, start=1):
        if n <= 1:
            emphasis = "high"
        elif rank <= max(1, (n + 2) // 3):
            emphasis = "high"
        elif rank <= max(2, (2 * n + 2) // 3):
            emphasis = "medium"
        else:
            emphasis = "standard"
        note = _bullet_recruiter_note(bc, emphasis, rank)
        out.append(
            {
                "evidence_id": bc.get("evidence_id"),
                "company": bc.get("company"),
                "section": bc.get("section") or "experience",
                "before": bc.get("before"),
                "after": bc.get("after"),
                "why": bc.get("why"),
                "rank": rank,
                "emphasis": emphasis,
                "recruiter_note": note,
                "mode": mode,
                "suggestions": suggestions,
            }
        )
    return out


def generate_structured_changes(resume_data: dict, role_profile: dict) -> List[Dict[str, Any]]:
    """
    Deterministic, safe change objects for Diff View v2.

    Rules:
    - Never emit before==after rows
    - Never emit low-confidence rows
    - Only use existing rewritten lines from ``rewrite_result`` (no fabricated experience)
    """
    mapping_result = role_profile.get("mapping_result") if isinstance(role_profile, dict) else {}
    rewrite_result = role_profile.get("rewrite_result") if isinstance(role_profile, dict) else {}
    job_signals = role_profile.get("job_signals") if isinstance(role_profile, dict) else None
    selected_summary = str(role_profile.get("selected_summary") or "").strip() if isinstance(role_profile, dict) else ""
    original_summary = str(role_profile.get("original_summary") or "").strip() if isinstance(role_profile, dict) else ""

    out: List[Dict[str, Any]] = []

    # Summary change: only when materially different and final selected summary is not weak.
    if original_summary and selected_summary and original_summary != selected_summary:
        if not is_weak_tailor_summary(selected_summary):
            out.append(
                {
                    "id": "tailor-structured-summary",
                    "section": "summary",
                    "before": original_summary,
                    "after": selected_summary,
                    "reason": "Improved summary clarity while keeping resume-grounded identity.",
                    "confidence": "high",
                    "signal": "summary_clarity",
                }
            )

    raw_bullets = rewrite_result.get("bullet_changes") if isinstance(rewrite_result, dict) else []
    if not isinstance(raw_bullets, list):
        return out

    for idx, bc in enumerate(raw_bullets):
        if not isinstance(bc, dict):
            continue
        before = str(bc.get("before") or "").strip()
        after = str(bc.get("after") or "").strip()
        if not before or not after or before == after:
            continue
        mode = str(bc.get("mode") or "").strip().lower()
        if mode and mode != "rewrite":
            continue

        evidence_id = str(bc.get("evidence_id") or "").strip()
        must_t, strong_t, weak_t = _touches_for_evidence(evidence_id, mapping_result, job_signals)
        clarity_delta = abs(_clarity_delta_words(before, after))
        reason_text = str(bc.get("why") or "").strip()
        confidence = "low"
        if must_t > 0 or strong_t > 0:
            confidence = "high"
        elif (weak_t > 0 and clarity_delta >= 2) or (clarity_delta >= 3 and bool(reason_text)):
            confidence = "medium"
        if confidence == "low":
            continue

        reason = reason_text
        if not reason:
            if confidence == "high":
                reason = "Strengthened role-relevant signal using existing evidence."
            else:
                reason = "Improved readability without changing factual content."

        section = str(bc.get("section") or "experience").strip().lower() or "experience"
        signal = evidence_id or None
        id_suffix = evidence_id if evidence_id else f"idx-{idx}"
        out.append(
            {
                "id": f"tailor-structured-{section}-{id_suffix}",
                "section": section,
                "before": before,
                "after": after,
                "reason": reason,
                "confidence": confidence,
                "signal": signal,
            }
        )
    return out


def _bullet_recruiter_note(bc: dict, emphasis: str, rank: int) -> str:
    why = str(bc.get("why") or "").strip()
    if why and not _sounds_debuggy(why):
        return _shorten(why, 160)
    v = rank % 3
    if emphasis == "high":
        opts = (
            "Sharpens a line that matters for the role; same facts.",
            "Makes the relevant line easier to read at a glance.",
            "Pulls the important detail forward without new claims.",
        )
        return opts[v]
    if emphasis == "medium":
        opts = (
            "Light wording cleanup; substance unchanged.",
            "Slightly clearer phrasing for a quick skim.",
            "Small readability tweak only.",
        )
        return opts[v]
    opts = (
        "Optional polish on a secondary line.",
        "Minor wording adjustment.",
        "Low-touch edit.",
    )
    return opts[v]


def _why_match_sort_key(row: dict) -> Tuple[float, int, int, int, float]:
    return _highlight_row_sort_key(row)


def _build_why_this_matches(
    mapping_result: dict, limit: int = 5, job_signals: Optional[dict] = None
) -> List[Dict[str, str]]:
    rows = [
        r
        for r in (mapping_result.get("requirement_matches") or [])
        if isinstance(r, dict) and r.get("classification") in ("strong", "weak")
    ]
    rows.sort(key=_why_match_sort_key, reverse=True)
    out: List[Dict[str, str]] = []
    seen_fp: set = set()
    for row in rows:
        if len(out) >= limit:
            break
        req_raw = str(row.get("requirement_text") or "")
        if not _requirement_row_allowed_for_output(req_raw, job_signals):
            continue
        if _requirement_text_is_non_fit_junk(req_raw):
            continue
        fp = _req_fingerprint(req_raw)
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        out.append(
            {
                "requirement": _shorten(req_raw, 120),
                "alignment": _alignment_label(row),
                "why": _public_match_why(row, job_signals),
                "best_evidence_text": _first_evidence_text(row),
            }
        )
    return out


def _recruiter_score_lines(score_result: dict) -> List[str]:
    overall = int(score_result.get("overall_score") or 0)
    dims = score_result.get("dimensions") or {}
    summ = score_result.get("summary") or {}
    cov = int(dims.get("requirement_coverage") or 0)
    ev = int(dims.get("evidence_strength") or 0)
    matched = int(summ.get("matched_requirements") or 0)
    missing = int(summ.get("missing_requirements") or 0)
    lines = [
        (
            f"Overall fit read: {overall}/100 — directional only, from the job text and what appears "
            f"on the resume (not a hiring prediction)."
        ),
    ]
    if overall <= 38 and matched <= 1:
        lines.append(
            "Limited overlap with the stated needs — the lines below stay with what is visible, not a flattering read."
        )
    if cov <= 8:
        lines.append(
            "Few role requirements are clearly demonstrated in the current resume lines — "
            f"where wording did line up, {matched} need(s) read as a clear fit."
        )
    else:
        lines.append(
            f"About {cov}% of stated needs show a clear read in your lines; "
            f"{matched} read as a clear fit where text was visible."
        )
    if missing:
        lines.append(
            f"{missing} asks still lack a clear line on the page — worth confirming whether they apply to you."
        )
    lines.append(
        f"Concrete detail in bullets reads around {ev}/100 on this rubric — skim aid only, not a verdict."
    )
    return lines


def _build_skim_preview_text(
    tailored_summary: str, prioritized_bullets: List[Dict[str, Any]], max_bullets: int = 3
) -> str:
    """
    Short preview block: summary plus top experience bullets (field name kept for API compatibility).
    """
    parts: List[str] = []
    ts = (tailored_summary or "").strip()
    if ts:
        parts.append(ts)
    for b in prioritized_bullets[:max_bullets]:
        if not isinstance(b, dict):
            continue
        after = str(b.get("after") or "").strip()
        if not after:
            continue
        co = str(b.get("company") or "").strip()
        prefix = f"{co} — " if co else ""
        parts.append(f"• {prefix}{_shorten(after, 200)}")
    if parts:
        return "\n\n".join(parts)
    return "Add a professional summary to preview tailored text here."


def _change_breakdown_summary_only(change_items: Any) -> List[Dict[str, Any]]:
    """Legacy field: summary row only so it does not duplicate prioritized bullets."""
    if not isinstance(change_items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in change_items:
        if isinstance(item, dict) and str(item.get("section") or "") == "summary":
            out.append(item)
    return out


def build_output_payload(
    resume_data: dict,
    job_signals: dict,
    mapping_result: dict,
    rewrite_result: dict,
    score_result: dict,
) -> Dict[str, Any]:
    tailored_summary = rewrite_result.get("tailored_summary") or ""
    ts_one = tailored_summary.strip()
    corpus_fb = _corpus_from_resume(resume_data)
    cl = corpus_fb.lower()
    if ts_one and (
        _summary_input_has_jd_pollution(tailored_summary)
        or is_employment_meta_line(ts_one)
        or is_benefits_line(ts_one)
    ):
        tailored_summary = _trim_redundant_words(
            _strip_bad_summary_phrases(_resume_grounded_poor_fit_summary(corpus_fb, cl, resume_data))
        )
    tailored_summary = _enforce_summary_resume_only(tailored_summary, corpus_fb, resume_data)

    post_gate = tailored_summary.strip()
    original_summary = _trim_redundant_words(
        _strip_bad_summary_phrases(_current_summary_text(resume_data).strip())
    )
    selected_source = "tailored_summary"
    fallback_reason: Optional[str] = None
    if is_weak_tailor_summary(post_gate):
        if original_summary and not is_weak_tailor_summary(original_summary):
            # Resume-sourced text: keep wording without re-running ``_enforce_summary_resume_only``,
            # which can collapse to a short template when the skim corpus is thin (still trimmed).
            tailored_summary = _trim_redundant_words(
                _strip_bad_summary_phrases(original_summary)
            ).strip()
            selected_source = "original_resume_summary"
            fallback_reason = (
                "Kept original summary because generated summary was too generic."
            )
        elif original_summary:
            fallback_reason = (
                "Generated summary matched weak heuristics; resume summary also looked weak — "
                "kept generated text."
            )

    logger.info(
        "TAILOR_SUMMARY_FALLBACK_DEBUG %s",
        json.dumps(
            {
                "selected_source": selected_source,
                "tailored_summary_preview": post_gate[:280],
                "original_summary_preview": original_summary[:280],
                "fallback_reason": fallback_reason,
            },
            ensure_ascii=False,
        ),
    )

    prioritized_bullet_changes_full = _prioritize_bullet_changes(
        rewrite_result, mapping_result, job_signals
    )
    prioritized_bullet_changes = [
        _sanitize_bullet_change_row(x, job_signals) for x in prioritized_bullet_changes_full[:5]
    ]

    tailored_resume_text = _build_skim_preview_text(
        tailored_summary, prioritized_bullet_changes, max_bullets=3
    )

    sections = {
        "summary": [tailored_summary] if tailored_summary else [],
        "experience": rewrite_result.get("tailored_experience_bullets") or [],
        "skills": rewrite_result.get("tailored_skills") or [],
    }

    summary_fallback_to_original = selected_source == "original_resume_summary"
    change_breakdown = _change_breakdown_summary_only(rewrite_result.get("change_items") or [])
    if summary_fallback_to_original:
        change_breakdown = [
            {
                "section": "summary",
                "before": original_summary,
                "after": original_summary,
                "why": "Kept original summary because generated summary was too generic.",
                "company": None,
            }
        ]
    elif change_breakdown and isinstance(change_breakdown[0], dict):
        row0 = dict(change_breakdown[0])
        row0["after"] = tailored_summary
        change_breakdown = [row0]

    structured_changes = generate_structured_changes(
        resume_data,
        {
            "mapping_result": mapping_result,
            "rewrite_result": rewrite_result,
            "job_signals": job_signals,
            "selected_summary": tailored_summary,
            "original_summary": original_summary,
        },
    )

    gap_analysis = _format_gap_analysis_lines(mapping_result, job_signals)

    top_alignment_highlights = _gather_top_alignment_highlights(mapping_result, 3, job_signals)
    top_gaps_to_watch = _gather_top_gaps_to_watch(mapping_result, 3, job_signals)
    why_this_matches = _build_why_this_matches(mapping_result, 5, job_signals)
    (
        top_alignment_highlights,
        top_gaps_to_watch,
        why_this_matches,
        gap_analysis,
    ) = _finalize_recruiter_requirement_output(
        top_alignment_highlights,
        top_gaps_to_watch,
        why_this_matches,
        gap_analysis,
        job_signals,
    )
    recruiter_score_notes = _recruiter_score_lines(score_result)

    score_for_response = dict(score_result)
    score_for_response["judgment_notes"] = recruiter_score_notes

    return {
        "tailored_resume_text": tailored_resume_text,
        "tailored_resume_sections": sections,
        "change_breakdown": change_breakdown,
        "gap_analysis": gap_analysis,
        "score_breakdown": score_for_response,
        "top_alignment_highlights": top_alignment_highlights,
        "top_gaps_to_watch": top_gaps_to_watch,
        "prioritized_bullet_changes": prioritized_bullet_changes,
        "structured_changes": structured_changes,
        "why_this_matches": why_this_matches,
    }
