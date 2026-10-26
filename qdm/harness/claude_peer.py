"""Claude peer caller: invokes a headless Claude Code instance as the QDM
questioner/reviewer/reporter/evolver (same-model homogeneous protocol variant).

Usage:
    python -m qdm.harness.claude_peer <request-file> <response-file> [stderr-log]

The request file contains the full role prompt (harness-generated packet).
The peer reads the file itself (like the Codex exec pattern), performs the
role, and its final message - which must be the decision JSON - is written
verbatim to the response file. Timestamps and the provider-reported model are
printed as JSON on stdout for the caller to record.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
TIMEOUT_SECONDS = 900


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    request_file = sys.argv[1]
    response_file = sys.argv[2]
    stderr_log = sys.argv[3] if len(sys.argv) > 3 else response_file + ".stderr.log"

    prompt = f"Read and follow exactly the instructions in the file {request_file}; return only the JSON decision."
    started = utc_now()
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", "--output-format", "json"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        timed_out = True
    else:
        stdout = proc.stdout
        stderr = proc.stderr
        timed_out = False
    finished = utc_now()

    with open(stderr_log, "w", encoding="utf-8") as handle:
        handle.write(stderr)

    result_text = stdout
    model_actual = ""
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(stdout.lstrip())
        if isinstance(obj, dict):
            result_text = obj.get("result", stdout)
            usage = obj.get("usage") or {}
            model_actual = obj.get("modelUsage", "").split(",")[0] if isinstance(
                obj.get("modelUsage"), str
            ) else ""
            if isinstance(obj.get("modelUsage"), dict) and obj["modelUsage"]:
                model_actual = next(iter(obj["modelUsage"]))
    except Exception:
        pass

    with open(response_file, "w", encoding="utf-8") as handle:
        handle.write(result_text.strip() + "\n")

    print(json.dumps({
        "status": "passed" if (not timed_out and proc.returncode == 0) else "failed",
        "timed_out": timed_out,
        "exit_code": None if timed_out else proc.returncode,
        "started_at": started,
        "finished_at": finished,
        "model_actual": model_actual,
        "response_bytes": len(result_text.strip().encode("utf-8")),
    }, ensure_ascii=False))
    return 0 if (not timed_out and proc.returncode == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
