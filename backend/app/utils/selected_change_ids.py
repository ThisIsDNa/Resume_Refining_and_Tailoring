"""Parse optional ``selected_change_ids`` multipart JSON from export routes (plumbing only)."""

from __future__ import annotations

import json
from typing import Any, List, Optional


def parse_selected_change_ids(raw: Optional[str]) -> List[str]:
    """
    Parse a JSON array of string ids from multipart form. Never raises.

    - ``None`` or all-whitespace → ``[]``
    - Invalid JSON, non-list JSON, or wrong element types → ``[]``
    - Strips each string; drops empties; dedupes while preserving first-seen order
    """
    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []
    try:
        data: Any = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            continue
        t = item.strip()
        if not t:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out
