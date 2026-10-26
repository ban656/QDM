"""Record data-file reads made by benchmark Python processes."""

from __future__ import annotations

import builtins
import json
import os
from pathlib import Path
from threading import Lock


_TRACE_FILE = os.environ.get("QDM_FILE_TRACE", "")
_LOCK = Lock()
_ORIGINAL_OPEN = builtins.open
_ORIGINAL_OS_OPEN = os.open


def _record(path: object) -> None:
    if not _TRACE_FILE or isinstance(path, int):
        return
    try:
        resolved = str(Path(os.fspath(path)).resolve())
        trace_resolved = str(Path(_TRACE_FILE).resolve())
    except (OSError, TypeError, ValueError):
        return
    if resolved == trace_resolved:
        return
    with _LOCK:
        with _ORIGINAL_OPEN(_TRACE_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"path": resolved}, ensure_ascii=False) + "\n")


def _open(file: object, mode: str = "r", *args: object, **kwargs: object):
    if "r" in mode or "+" in mode:
        _record(file)
    return _ORIGINAL_OPEN(file, mode, *args, **kwargs)


def _os_open(path: object, flags: int, *args: object, **kwargs: object):
    write_only = flags & getattr(os, "O_WRONLY", 1)
    if not write_only:
        _record(path)
    return _ORIGINAL_OS_OPEN(path, flags, *args, **kwargs)


builtins.open = _open
os.open = _os_open
