#!/usr/bin/env python3
"""Validate the EBA Analyst cross-agent memory structure."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "docs" / "memory"

REQUIRED_FILES = [
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / "GEMINI.md",
    MEMORY / "PROJECT.md",
    MEMORY / "CURRENT.md",
    MEMORY / "DECISIONS.md",
]

REQUIRED_HEADINGS = {
    "AGENTS.md": [
        "Purpose",
        "Before starting work",
        "Source of truth",
    ],
    "PROJECT.md": [
        "Overview",
        "Architecture",
        "Database",
        "Tests and database safety",
    ],
    "CURRENT.md": [
        "Status",
        "Current work",
        "Next step",
    ],
    "DECISIONS.md": [
        "D001",
        "D002",
        "D003",
    ],
}

SESSION_SECTIONS = [
    "Goal",
    "Changes",
    "Verification",
    "Remaining work",
]

errors: list[str] = []
warnings: list[str] = []


def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"Cannot read {path.relative_to(ROOT)}: {exc}")
        return ""


def check_required_files() -> None:
    for path in REQUIRED_FILES:
        if not path.is_file():
            errors.append(f"Missing file: {path.relative_to(ROOT)}")


def check_headings() -> None:
    for filename, headings in REQUIRED_HEADINGS.items():
        path = ROOT / filename if filename == "AGENTS.md" else MEMORY / filename
        if not path.is_file():
            continue

        content = read_file(path)

        for heading in headings:
            pattern = rf"(?m)^#+\s+.*{re.escape(heading)}.*$"
            if not re.search(pattern, content, re.IGNORECASE):
                errors.append(
                    f"{path.relative_to(ROOT)}: missing heading containing '{heading}'"
                )


def check_agent_references() -> None:
    for filename in ("CLAUDE.md", "GEMINI.md"):
        path = ROOT / filename
        if not path.is_file():
            continue

        content = read_file(path)

        for reference in (
            "AGENTS.md",
            "docs/memory/CURRENT.md",
            "docs/memory/PROJECT.md",
        ):
            if reference not in content:
                errors.append(f"{filename}: missing reference to {reference}")


def check_memory_artifacts() -> None:
    files = [
        MEMORY / "PROJECT.md",
        MEMORY / "CURRENT.md",
        MEMORY / "DECISIONS.md",
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "GEMINI.md",
    ]

    for path in files:
        if not path.is_file():
            continue

        content = read_file(path)

        if re.search(r"(?m)^.*(?:PROJECT_MEMORY_EOF|PYTHON_VALIDATOR)\d*\s*$", content):
            errors.append(
                f"{path.relative_to(ROOT)}: accidental heredoc delimiter found"
            )


def check_sessions() -> None:
    sessions_dir = MEMORY / "sessions"

    if not sessions_dir.is_dir():
        errors.append("Missing directory: docs/memory/sessions/")
        return

    sessions = sorted(sessions_dir.glob("*.md"))

    if not sessions:
        errors.append("No session notes found in docs/memory/sessions/")
        return

    filename_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")

    for path in sessions:
        if not filename_pattern.match(path.name):
            errors.append(f"Invalid session filename: {path.name}")
            continue

        content = read_file(path)

        for section in SESSION_SECTIONS:
            pattern = rf"(?m)^#+\s+.*{re.escape(section)}.*$"
            if not re.search(pattern, content, re.IGNORECASE):
                errors.append(
                    f"{path.relative_to(ROOT)}: missing section '{section}'"
                )


def main() -> int:
    print("EBA Analyst — Memory validation")
    print(f"Project: {ROOT}")
    print()

    check_required_files()
    check_headings()
    check_agent_references()
    check_memory_artifacts()
    check_sessions()

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  WARNING: {warning}")

    if errors:
        print(f"FAILED: {len(errors)} problem(s) found.")
        for error in errors:
            print(f"  ERROR: {error}")
        return 1

    print("SUCCESS: memory structure is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
