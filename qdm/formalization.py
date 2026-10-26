"""Method-neutral problem formalization package (P1) validation.

The package is a reporting checkpoint, not a prescription for how a solver
must reason.  QDM and baseline protocols may construct it differently, but a
run cannot start solution design until the package is structurally closed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


SCHEMA_VERSION = "problem_formalization_package_v2"
ITEM_SECTIONS = (
    "requirements",
    "boundaries",
    "operational_targets",
    "observables",
    "variables",
    "relations",
    "constraints",
    "assumptions",
    "uncertainties",
    "validation_requirements",
)
REQUIRED_NONEMPTY_SECTIONS = (
    "requirements",
    "boundaries",
    "operational_targets",
    "variables",
    "relations",
    "constraints",
    "assumptions",
    "uncertainties",
    "validation_requirements",
)
VALID_REQUIREMENT_TYPES = {"goal", "functional", "quality", "data", "reporting"}
VALID_CONSTRAINT_TYPES = {"hard", "soft"}
VALID_UNCERTAINTY_TYPES = {"structural", "data", "parameter", "model"}
VALID_CLOSURE_STATUSES = {"draft", "blocked", "frozen"}


def template(problem_id: str = "") -> Dict[str, Any]:
    """Return an intentionally unfilled package template."""
    return {
        "schema_version": SCHEMA_VERSION,
        "problem_id": problem_id,
        "source_anchors": [],
        "requirements": [],
        "boundaries": [],
        "operational_targets": [],
        "observables": [],
        "variables": [],
        "relations": [],
        "constraints": [],
        "assumptions": [],
        "uncertainties": [],
        "identifiability": {
            "status": "not_assessed",
            "confounders": [],
            "non_identifiable_items": [],
            "resolution_or_consequence": "",
        },
        "validation_requirements": [],
        "traceability": [],
        "unresolved_items": [],
        "closure": {
            "status": "draft",
            "blocking_item_ids": [],
            "non_blocking_item_ids": [],
            "closure_rationale": "",
        },
    }


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ids(items: Any, section: str, issues: List[str]) -> Set[str]:
    if not isinstance(items, list):
        issues.append(f"{section} must be a list")
        return set()
    found: Set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f"{section}[{index}] must be an object")
            continue
        item_id = item.get("id")
        if not _nonempty(item_id):
            issues.append(f"{section}[{index}].id is required")
        elif item_id in found:
            issues.append(f"duplicate id in {section}: {item_id}")
        else:
            found.add(item_id)
    return found


def _require_text(item: Dict[str, Any], keys: Iterable[str], label: str, issues: List[str]) -> None:
    for key in keys:
        if not _nonempty(item.get(key)):
            issues.append(f"{label}.{key} is required")


def validate_package(package: Dict[str, Any], require_frozen: bool = True) -> List[str]:
    """Return deterministic, schema-level P1 defects.

    Semantic quality is deliberately left to blinded judges.  These checks
    only ensure that claims are explicit, linked, and capable of being tested.
    """
    issues: List[str] = []
    if not isinstance(package, dict):
        return ["formalization package must be a JSON object"]
    if package.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"schema_version must be {SCHEMA_VERSION}")
    if not _nonempty(package.get("problem_id")):
        issues.append("problem_id is required")

    anchors = package.get("source_anchors")
    anchor_ids = _ids(anchors, "source_anchors", issues)
    if not anchor_ids:
        issues.append("source_anchors must be non-empty")
    for index, anchor in enumerate(anchors if isinstance(anchors, list) else []):
        if not isinstance(anchor, dict):
            continue
        _require_text(anchor, ("source", "locator", "quote_or_description"), f"source_anchors[{index}]", issues)

    section_ids: Dict[str, Set[str]] = {}
    all_item_ids: Set[str] = set()
    for section in ITEM_SECTIONS:
        values = package.get(section)
        ids = _ids(values, section, issues)
        section_ids[section] = ids
        overlap = all_item_ids.intersection(ids)
        if overlap:
            issues.append(f"ids must be globally unique; repeated: {sorted(overlap)}")
        all_item_ids.update(ids)
        if section in REQUIRED_NONEMPTY_SECTIONS and not ids:
            issues.append(f"{section} must contain at least one item")

    requirements = package.get("requirements", [])
    for index, item in enumerate(requirements if isinstance(requirements, list) else []):
        if not isinstance(item, dict):
            continue
        label = f"requirements[{index}]"
        _require_text(item, ("statement", "priority", "verification"), label, issues)
        if item.get("type") not in VALID_REQUIREMENT_TYPES:
            issues.append(f"{label}.type is invalid")
        refs = item.get("source_anchor_ids")
        if not isinstance(refs, list) or not refs:
            issues.append(f"{label}.source_anchor_ids must be non-empty")
        elif set(refs) - anchor_ids:
            issues.append(f"{label} references unknown source anchors: {sorted(set(refs) - anchor_ids)}")

    for section, text_keys in {
        "boundaries": ("statement", "inside_or_outside", "consequence"),
        "operational_targets": ("target", "metric", "success_predicate"),
        "observables": ("name", "acquisition_method", "unit"),
        "variables": ("symbol", "meaning", "role", "unit", "domain"),
        "relations": ("expression_or_rule", "applicability", "evidence"),
        "assumptions": ("statement", "justification", "consequence_if_false"),
        "validation_requirements": ("target", "method", "pass_fail_predicate", "failure_action"),
    }.items():
        for index, item in enumerate(package.get(section, []) if isinstance(package.get(section), list) else []):
            if isinstance(item, dict):
                _require_text(item, text_keys, f"{section}[{index}]", issues)

    for index, item in enumerate(package.get("constraints", []) if isinstance(package.get("constraints"), list) else []):
        if not isinstance(item, dict):
            continue
        label = f"constraints[{index}]"
        _require_text(item, ("statement", "scope", "source", "executable_check", "failure_action"), label, issues)
        if item.get("type") not in VALID_CONSTRAINT_TYPES:
            issues.append(f"{label}.type must be hard or soft")

    for index, item in enumerate(package.get("uncertainties", []) if isinstance(package.get("uncertainties"), list) else []):
        if not isinstance(item, dict):
            continue
        label = f"uncertainties[{index}]"
        _require_text(item, ("source", "affected_items", "analysis_or_mitigation"), label, issues)
        if item.get("type") not in VALID_UNCERTAINTY_TYPES:
            issues.append(f"{label}.type is invalid")

    identifiability = package.get("identifiability")
    if not isinstance(identifiability, dict):
        issues.append("identifiability must be an object")
    else:
        if identifiability.get("status") not in {"identified", "partially_identified", "not_identifiable", "not_applicable"}:
            issues.append("identifiability.status must record an assessed state")
        if not isinstance(identifiability.get("confounders"), list):
            issues.append("identifiability.confounders must be a list")
        if not isinstance(identifiability.get("non_identifiable_items"), list):
            issues.append("identifiability.non_identifiable_items must be a list")
        if not _nonempty(identifiability.get("resolution_or_consequence")):
            issues.append("identifiability.resolution_or_consequence is required")

    traceability = package.get("traceability")
    trace_ids = _ids(traceability, "traceability", issues)
    traced_requirements: Set[str] = set()
    valid_targets = all_item_ids | trace_ids
    for index, item in enumerate(traceability if isinstance(traceability, list) else []):
        if not isinstance(item, dict):
            continue
        label = f"traceability[{index}]"
        requirement_id = item.get("requirement_id")
        if requirement_id not in section_ids.get("requirements", set()):
            issues.append(f"{label}.requirement_id is unknown")
        else:
            traced_requirements.add(requirement_id)
        refs = item.get("specification_item_ids")
        if not isinstance(refs, list) or not refs:
            issues.append(f"{label}.specification_item_ids must be non-empty")
        elif set(refs) - valid_targets:
            issues.append(f"{label} references unknown specification items: {sorted(set(refs) - valid_targets)}")
        validation_ids = item.get("validation_requirement_ids")
        if not isinstance(validation_ids, list) or not validation_ids:
            issues.append(f"{label}.validation_requirement_ids must be non-empty")
        elif set(validation_ids) - section_ids.get("validation_requirements", set()):
            issues.append(f"{label} references unknown validation items")
    untraced = section_ids.get("requirements", set()) - traced_requirements
    if untraced:
        issues.append(f"requirements lack traceability: {sorted(untraced)}")

    unresolved = package.get("unresolved_items")
    unresolved_ids = _ids(unresolved, "unresolved_items", issues)
    blockers = set()
    non_blockers = set()
    for index, item in enumerate(unresolved if isinstance(unresolved, list) else []):
        if not isinstance(item, dict):
            continue
        _require_text(item, ("question", "consequence", "disposition"), f"unresolved_items[{index}]", issues)
        if item.get("classification") == "blocker":
            blockers.add(item.get("id"))
        elif item.get("classification") == "non_blocker":
            non_blockers.add(item.get("id"))
        else:
            issues.append(f"unresolved_items[{index}].classification is invalid")

    closure = package.get("closure")
    if not isinstance(closure, dict):
        issues.append("closure must be an object")
    else:
        status = closure.get("status")
        if status not in VALID_CLOSURE_STATUSES:
            issues.append("closure.status is invalid")
        declared_blockers = set(closure.get("blocking_item_ids", []))
        declared_non_blockers = set(closure.get("non_blocking_item_ids", []))
        if declared_blockers != blockers:
            issues.append("closure.blocking_item_ids do not match unresolved blockers")
        if declared_non_blockers != non_blockers:
            issues.append("closure.non_blocking_item_ids do not match unresolved non-blockers")
        if (declared_blockers | declared_non_blockers) - unresolved_ids:
            issues.append("closure references unknown unresolved items")
        if not _nonempty(closure.get("closure_rationale")):
            issues.append("closure.closure_rationale is required")
        if status == "frozen" and blockers:
            issues.append("a frozen package cannot contain unresolved blockers")
        if require_frozen and status != "frozen":
            issues.append("closure.status must be frozen")
    return issues


def load_and_validate(path: str | Path, require_frozen: bool = True) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        package = json.load(handle)
    issues = validate_package(package, require_frozen=require_frozen)
    if issues:
        raise ValueError("Invalid formalization package: " + "; ".join(issues))
    return package


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or validate a P1 formalization package")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("template")
    create.add_argument("--output", required=True)
    create.add_argument("--problem-id", default="")
    validate = sub.add_parser("validate")
    validate.add_argument("--input", required=True)
    validate.add_argument("--allow-draft", action="store_true")
    args = parser.parse_args()
    if args.command == "template":
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(template(args.problem_id), ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)
        return 0
    try:
        load_and_validate(args.input, require_frozen=not args.allow_draft)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "passed", "input": str(Path(args.input).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
