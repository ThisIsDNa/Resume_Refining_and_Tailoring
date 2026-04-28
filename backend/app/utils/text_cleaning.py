"""Text normalization helpers for JD and resume text."""

from __future__ import annotations


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace and strip each line; join lines with single newlines."""
    if not text:
        return ""
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def trim_safe(text: str, max_chars: int | None = None) -> str:
    """Trim edges; optionally cap length without raising."""
    s = text.strip()
    if max_chars is not None and len(s) > max_chars:
        return s[:max_chars].rstrip() + "…"
    return s
