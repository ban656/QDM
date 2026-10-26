"""Versioned pattern library inspired by Voyager's skill memory.

Voyager stores executable skills after successful Minecraft tasks.  This module
stores reusable modeling structures after completed mathematical-modeling runs:
question patterns, modeling patterns, algorithm modules, validation questions,
writing patterns, policy update proposals, and anti-patterns.

It is intentionally file-based and approval-friendly.  The library records
proposals; applying them to prompts or policy remains an explicit human choice.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MMA_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
if MMA_ROOT not in sys.path:
    sys.path.insert(0, MMA_ROOT)

from qdm.evolution.prompt import build_distillation_prompt, build_retrieval_context


CATEGORIES = [
    "question_patterns",
    "modeling_patterns",
    "algorithm_modules",
    "validation_questions",
    "writing_patterns",
    "policy_updates",
    "anti_patterns",
]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_json_object(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def ensure_library(root: str) -> Dict[str, str]:
    dirs = {
        "root": root,
        "entries": os.path.join(root, "entries"),
        "prompts": os.path.join(root, "prompts"),
        "reports": os.path.join(root, "reports"),
    }
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    index_path = os.path.join(root, "pattern_index.json")
    if not os.path.isfile(index_path):
        write_json(index_path, make_empty_index())
    return dirs


def make_empty_index() -> Dict[str, Any]:
    return {
        "schema_version": "questioner_evolution_v1",
        "created_at": now(),
        "updated_at": now(),
        "next_id": 1,
        "entries": [],
        "categories": {category: [] for category in CATEGORIES},
    }


def load_index(root: str) -> Dict[str, Any]:
    ensure_library(root)
    return read_json(os.path.join(root, "pattern_index.json"))


def save_index(root: str, index: Dict[str, Any]) -> None:
    index["updated_at"] = now()
    write_json(os.path.join(root, "pattern_index.json"), index)


def stable_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text.lower())


def score_entry(entry: Dict[str, Any], query_tokens: Iterable[str]) -> float:
    text = stable_text(entry)
    tokens = set(tokenize(text))
    score = 0.0
    for token in query_tokens:
        if token in tokens:
            score += 1.0
        elif token and token in text.lower():
            score += 0.3
    return score


def next_entry_id(index: Dict[str, Any]) -> str:
    value = int(index.get("next_id", 1))
    index["next_id"] = value + 1
    return f"EV{value:05d}"


def category_item_id(item: Dict[str, Any], category: str) -> str:
    for key in ["pattern_id", "module_id", "check_id", "id", "name"]:
        if item.get(key):
            return str(item[key])
    return category


def add_distillation(root: str, distillation: Dict[str, Any], source: str = "") -> Tuple[str, str]:
    dirs = ensure_library(root)
    index = load_index(root)
    entry_id = next_entry_id(index)
    entry = {
        "entry_id": entry_id,
        "created_at": now(),
        "source": source,
        "source_problem_id": distillation.get("source_problem_id", ""),
        "distillation_summary": distillation.get("distillation_summary", ""),
        "status": "proposed",
        "distillation": {category: distillation.get(category, []) for category in CATEGORIES},
    }
    entry_path = os.path.join(dirs["entries"], f"{entry_id}.json")
    write_json(entry_path, entry)

    index.setdefault("entries", []).append(
        {
            "entry_id": entry_id,
            "created_at": entry["created_at"],
            "source_problem_id": entry["source_problem_id"],
            "summary": entry["distillation_summary"],
            "path": os.path.abspath(entry_path),
            "status": "proposed",
        }
    )
    index.setdefault("categories", {category: [] for category in CATEGORIES})
    for category in CATEGORIES:
        for item in distillation.get(category, []) or []:
            index["categories"].setdefault(category, []).append(
                {
                    "entry_id": entry_id,
                    "item_id": category_item_id(item, category),
                    "summary": item.get("question")
                    or item.get("name")
                    or item.get("suggested_change")
                    or item.get("symptom")
                    or stable_text(item)[:160],
                }
            )
    save_index(root, index)
    report_path = os.path.join(dirs["reports"], f"{entry_id}_summary.md")
    write_text(report_path, format_entry_markdown(entry))
    return entry_path, report_path


def format_entry_markdown(entry: Dict[str, Any]) -> str:
    lines = [
        f"# Evolution Entry {entry['entry_id']}",
        "",
        f"- source_problem_id: {entry.get('source_problem_id', '')}",
        f"- status: {entry.get('status', '')}",
        "",
        "## Summary",
        "",
        entry.get("distillation_summary", "") or "Not specified.",
        "",
    ]
    distillation = entry.get("distillation", {})
    for category in CATEGORIES:
        items = distillation.get(category, []) or []
        lines.extend([f"## {category}", ""])
        if not items:
            lines.extend(["- None", ""])
            continue
        for item in items:
            lines.append(f"- `{category_item_id(item, category)}`: {item.get('name') or item.get('question') or item.get('suggested_change') or item.get('symptom') or stable_text(item)[:160]}")
        lines.append("")
    return "\n".join(lines)


def retrieve(root: str, query: str, top_k: int = 5, category: str = "") -> Dict[str, Any]:
    ensure_library(root)
    index = load_index(root)
    query_tokens = tokenize(query)
    scored = []
    for meta in index.get("entries", []):
        path = meta.get("path", "")
        if not path or not os.path.isfile(path):
            continue
        entry = read_json(path)
        if category:
            entry_for_score = entry.get("distillation", {}).get(category, [])
        else:
            entry_for_score = entry
        score = score_entry(entry_for_score, query_tokens)
        if score > 0 or not query_tokens:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("entry_id", "")))
    selected = [entry for _, entry in scored[:top_k]]
    return {
        "query": query,
        "category": category,
        "top_k": top_k,
        "matches": selected,
    }


def write_distillation_prompt(
    library_root: str,
    state_path: str,
    solution_path: str,
    feedback_path: str = "",
    output_path: str = "",
) -> str:
    dirs = ensure_library(library_root)
    state = read_json(state_path)
    solution_text = read_text(solution_path)
    feedback_text = read_text(feedback_path) if feedback_path else ""
    prompt = build_distillation_prompt(state, solution_text, feedback_text)
    if not output_path:
        title = state.get("problem", {}).get("title", "problem")
        safe_title = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(title)).strip("_") or "problem"
        output_path = os.path.join(dirs["prompts"], f"{safe_title}_distill.md")
    write_text(output_path, prompt)
    return output_path


def import_distillation(library_root: str, answer_path: str) -> Tuple[str, str]:
    raw = read_text(answer_path)
    data = parse_json_object(raw)
    return add_distillation(library_root, data, source=os.path.abspath(answer_path))


def write_retrieval_context(
    library_root: str,
    query: str,
    output_path: str,
    top_k: int = 5,
    category: str = "",
) -> str:
    result = retrieve(library_root, query, top_k=top_k, category=category)
    context = build_retrieval_context(result, query)
    write_text(output_path, context)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Questioner-guided structural evolution library.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prompt = sub.add_parser("distill-prompt", help="Write a prompt for structural distillation.")
    p_prompt.add_argument("--library", required=True)
    p_prompt.add_argument("--state", required=True)
    p_prompt.add_argument("--solution", required=True)
    p_prompt.add_argument("--feedback", default="")
    p_prompt.add_argument("--output", default="")

    p_import = sub.add_parser("import", help="Import a distillation JSON answer into the pattern library.")
    p_import.add_argument("--library", required=True)
    p_import.add_argument("--answer", required=True)

    p_retrieve = sub.add_parser("retrieve", help="Retrieve reusable patterns for a future problem.")
    p_retrieve.add_argument("--library", required=True)
    p_retrieve.add_argument("--query", required=True)
    p_retrieve.add_argument("--output", required=True)
    p_retrieve.add_argument("--top-k", type=int, default=5)
    p_retrieve.add_argument("--category", default="")

    p_init = sub.add_parser("init", help="Initialize an empty evolution library.")
    p_init.add_argument("--library", required=True)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "init":
        ensure_library(args.library)
        print(f"Evolution library initialized: {args.library}")
    elif args.command == "distill-prompt":
        path = write_distillation_prompt(
            args.library,
            args.state,
            args.solution,
            feedback_path=args.feedback,
            output_path=args.output,
        )
        print(f"Distillation prompt written: {path}")
    elif args.command == "import":
        entry_path, report_path = import_distillation(args.library, args.answer)
        print(f"Evolution entry imported: {entry_path}")
        print(f"Summary report written: {report_path}")
    elif args.command == "retrieve":
        path = write_retrieval_context(
            args.library,
            args.query,
            args.output,
            top_k=args.top_k,
            category=args.category,
        )
        print(f"Retrieval context written: {path}")


if __name__ == "__main__":
    main()
