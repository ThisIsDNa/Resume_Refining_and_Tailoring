"""Temporary upload handling."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import UploadFile


async def save_upload_to_temp(upload: UploadFile, suffix: str = ".docx") -> Path:
    """Write upload to a temp file; caller should delete when done."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    dest = Path(path)
    content = await upload.read()
    dest.write_bytes(content)
    return dest


def cleanup_temp_file(path: Optional[Path]) -> None:
    """Best-effort delete of a temp file."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
