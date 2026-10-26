"""Freeze code-produced numbers before paper writing.

This is a lightweight adapter from QDM-Agent's auto workspace to the
MathModeling-skills results-to-paper discipline:

code/results -> frozen_numbers.json -> solution package -> paper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


SCRIPT_TIMEOUT_SECONDS = 180
SHIELD_PATTERNS = [
    re.compile(r"Shielding time:\s*([0-9]+(?:\.[0-9]+)?)\s*s", re.I),
    re.compile(r"Max shielding time:\s*([0-9]+(?:\.[0-9]+)?)\s*s", re.I),
    re.compile(r"Total shielding time:\s*([0-9]+(?:\.[0-9]+)?)\s*s", re.I),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def workspace_path(workspace: str, *parts: str) -> str:
    return os.path.join(workspace, *parts)


def discover_scripts(code_dir: str) -> List[str]:
    if not os.path.isdir(code_dir):
        return []
    scripts = []
    for name in sorted(os.listdir(code_dir)):
        if not name.endswith(".py"):
            continue
        if name.startswith("_"):
            continue
        if name in {"smoke_core.py"}:
            continue
        scripts.append(os.path.join(code_dir, name))
    return scripts


def run_script(script: str, cwd: str, timeout: int) -> Dict[str, Any]:
    started_at = now_iso()
    try:
        proc = subprocess.run(
            [sys.executable, script],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "script": os.path.relpath(script, cwd).replace("\\", "/"),
            "started_at": started_at,
            "finished_at": now_iso(),
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "script": os.path.relpath(script, cwd).replace("\\", "/"),
            "started_at": started_at,
            "finished_at": now_iso(),
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timeout": True,
        }


def parse_json_from_stdout(stdout: str) -> Optional[Any]:
    text = stdout.strip()
    if not text:
        return None
    # Try full stdout as JSON first
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    # Search for JSON anywhere in stdout (common when log output precedes JSON)
    # Strategy 1: check each line for single-line JSON
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    # Strategy 2: find the first top-level JSON object or array with regex
    for pattern in [r"\{.*\}", r"\[.*\]"]:
        match = re.search(pattern, text, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    return None


def flatten_json_claims(prefix: str, data: Any, source: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            next_prefix = f"{prefix}_{key}" if prefix else str(key)
            claims.extend(flatten_json_claims(next_prefix, value, source))
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            claims.extend(flatten_json_claims(f"{prefix}_{idx}", value, source))
    elif isinstance(data, (int, float, bool)):
        claims.append(
            {
                "id": sanitize_claim_id(prefix),
                "value": data,
                "unit": infer_unit(prefix),
                "source_file": source,
                "source_kind": "json_stdout",
            }
        )
    return claims


def infer_unit(text: str) -> str:
    lowered = text.lower()
    if "time" in lowered or "shield" in lowered and lowered.endswith("_s"):
        return "s"
    if "speed" in lowered:
        return "m/s"
    if "direction" in lowered or "dir" in lowered:
        return "deg"
    if "release" in lowered or "detonation" in lowered or lowered.endswith("_rel") or lowered.endswith("_det"):
        return "s"
    return ""


def sanitize_claim_id(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "claim"


def script_prefix(script_name: str) -> str:
    base = os.path.splitext(os.path.basename(script_name))[0]
    return sanitize_claim_id(base)


def parse_text_claims(stdout: str, script_name: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    prefix = script_prefix(script_name)
    for line_no, line in enumerate(stdout.splitlines(), start=1):
        for pattern in SHIELD_PATTERNS:
            match = pattern.search(line)
            if match:
                claims.append(
                    {
                        "id": f"{prefix}_shielding_time_s",
                        "value": float(match.group(1)),
                        "unit": "s",
                        "source_file": script_name,
                        "source_stdout_line": line_no,
                        "source_kind": "text_stdout",
                    }
                )
    return claims


def extract_claims(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    source = run["script"]
    data = parse_json_from_stdout(run.get("stdout", ""))
    if data is not None:
        return flatten_json_claims(script_prefix(source), data, source)
    return parse_text_claims(run.get("stdout", ""), source)


def build_freeze(workspace: str, timeout: int) -> Dict[str, Any]:
    code_dir = workspace_path(workspace, "claude_workspace", "final", "code")
    scripts = discover_scripts(code_dir)
    runs_dir = workspace_path(workspace, "claude_workspace", "writing", "runs")
    runs = [run_script(script, code_dir, timeout) for script in scripts]
    claims: List[Dict[str, Any]] = []
    for run in runs:
        if run.get("exit_code") == 0 and not run.get("timeout"):
            claims.extend(extract_claims(run))
            # Persist the full structured payload so the writing package can
            # reference complete engineering detail without truncation.
            payload = parse_json_from_stdout(run.get("stdout") or "")
            if isinstance(payload, dict):
                payload_path = os.path.join(runs_dir, f"{os.path.basename(run.get('script', 'run'))}.payload.json")
                write_json(payload_path, payload)
                run["payload_path"] = os.path.relpath(payload_path, workspace).replace("\\", "/")

    source_files = []
    for script in scripts:
        source_files.append(
            {
                "path": os.path.relpath(script, workspace).replace("\\", "/"),
                "sha256": file_sha256(script),
                "mtime": datetime.fromtimestamp(os.path.getmtime(script), timezone.utc).isoformat(),
            }
        )

    return {
        "schema_version": "qdm_frozen_numbers_v1",
        "frozen_at": now_iso(),
        "frozen_by": "qdm/writing/freeze.py",
        "workspace": os.path.abspath(workspace),
        "source_files": source_files,
        "runs": runs,
        "claims": claims,
        "status": "passed" if claims and all(r.get("exit_code") == 0 and not r.get("timeout") for r in runs) else "failed",
    }


def build_solution_package(freeze: Dict[str, Any]) -> str:
    lines = [
        "# Solution Package For Writer",
        "",
        "This package is the only allowed source for numerical paper claims. It",
        "carries the full engineering detail of the run: frozen claims, complete",
        "structured results (checkpoint series, POC curves, convergence and",
        "sensitivity tables, portfolios), and full payload files per script.",
        "",
        f"- Freeze status: `{freeze.get('status')}`",
        f"- Frozen at: `{freeze.get('frozen_at')}`",
        f"- Source scripts: {len(freeze.get('source_files', []))}",
        f"- Frozen claims: {len(freeze.get('claims', []))}",
        "",
        "## Frozen Claims",
        "",
        "| Claim ID | Value | Unit | Source |",
        "|---|---:|---|---|",
    ]
    for claim in freeze.get("claims", []):
        lines.append(
            f"| `{claim.get('id')}` | {claim.get('value')} | {claim.get('unit', '')} | `{claim.get('source_file')}` |"
        )
    lines.extend(["", "## Script Runs and Full Payloads", ""])
    for run in freeze.get("runs", []):
        lines.extend(
            [
                f"### `{run.get('script')}`",
                "",
                f"- exit_code: `{run.get('exit_code')}`",
                f"- timeout: `{run.get('timeout')}`",
                f"- full payload: `{run.get('payload_path', 'n/a')}`",
                "",
            ]
        )
        if run.get("stderr"):
            lines.extend(["stderr:", "", "```text", run["stderr"].strip()[:2000], "```", ""])
    lines.extend(["", "## Structured Results (full, per script)", ""])
    for run in freeze.get("runs", []):
        block = structured_results(run)
        if block:
            lines.append(block)
            lines.append("")
    return "\n".join(lines) + "\n"


def _fmt_scalar(value: Any) -> str:
    """Render a scalar for the structured-results markdown."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}".rstrip("0").rstrip(".") if abs(value) < 1e12 else str(value)
    if value is None:
        return "null"
    return str(value)


def _table_md(items: List[Dict[str, Any]], level: int) -> str:
    """Render a homogeneous list of dicts as a markdown table."""
    keys: List[str] = []
    for item in items:
        for key in item.keys():
            if key not in keys:
                keys.append(key)
    pad = "  " * level
    lines = [f"{pad}| {' | '.join(keys)} |", f"{pad}|{'---|' * len(keys)}"]
    for item in items:
        lines.append(f"{pad}| {' | '.join(_fmt_scalar(item.get(k)) for k in keys)} |")
    return "\n".join(lines) + "\n"


def _json_to_markdown(value: Any, level: int = 0) -> str:
    """Render a JSON fragment as markdown: tables for homogeneous dict lists,
    nested sections for dicts, bullets for scalars."""
    pad = "  " * level
    lines: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, list) and item and all(isinstance(i, dict) for i in item):
                lines.append(f"{pad}- **{key}**")
                lines.append(_table_md(item, level + 1))
            elif isinstance(item, dict):
                lines.append(f"{pad}- **{key}**")
                lines.append(_json_to_markdown(item, level + 1).rstrip())
            else:
                lines.append(f"{pad}- **{key}**: {_fmt_scalar(item)}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, dict):
                lines.append(f"{pad}- item {index}:")
                lines.append(_json_to_markdown(item, level + 1).rstrip())
            else:
                lines.append(f"{pad}- {_fmt_scalar(item)}")
    else:
        lines.append(f"{pad}- {_fmt_scalar(value)}")
    return "\n".join(lines) + "\n"


def structured_results(run: Dict[str, Any]) -> str:
    """Render the full structured results of a script run as markdown
    (checkpoints, POC curves, convergence, sensitivity, portfolios), so the
    writing package carries the engineering detail of the run itself."""
    payload = parse_json_from_stdout(run.get("stdout") or "")
    if not isinstance(payload, dict) or not payload.get("results"):
        return ""
    provenance = payload.get("provenance", {})
    head = [f"### Structured results — `{run.get('script')}`", ""]
    if isinstance(provenance, dict) and provenance:
        head.append("**Provenance**")
        head.append(_json_to_markdown(provenance).rstrip())
        head.append("")
    body = _json_to_markdown(payload.get("results", {}))
    return "\n".join(head) + body


def load_optional_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_freeze_outputs(workspace: str, timeout: int) -> Dict[str, str]:
    freeze = build_freeze(workspace, timeout)
    writing_dir = workspace_path(workspace, "claude_workspace", "writing")
    frozen_path = os.path.join(writing_dir, "frozen_numbers.json")
    package_path = os.path.join(writing_dir, "solution_package_for_writer.md")
    write_json(frozen_path, freeze)
    write_text(package_path, build_solution_package(freeze))
    return {
        "frozen_numbers": frozen_path,
        "solution_package_for_writer": package_path,
        "status": freeze.get("status", "failed"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze code-produced numbers before paper writing.")
    parser.add_argument("--workspace", required=True, help="QDM auto benchmark workspace.")
    parser.add_argument("--timeout", type=int, default=SCRIPT_TIMEOUT_SECONDS, help="Timeout per script in seconds.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = write_freeze_outputs(os.path.abspath(args.workspace), args.timeout)
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    if paths.get("status") != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()
