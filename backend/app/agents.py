from __future__ import annotations


DEFAULT_PROJECT_RULES = """- Work only inside this project folder unless explicitly told otherwise.
- Read files before editing and keep changes scoped to the requested task.
- Preserve user changes and avoid destructive git or filesystem operations."""

HARD_SAFETY_RULES = """- Do not modify files outside this project folder.
- Do not install dependencies without explaining why.
- Do not execute install scripts automatically.
- Do not add telemetry.
- Do not add cloud services unless explicitly requested.
- Do not store secrets in source files.
- Prefer small, reviewable changes.
- Explain security-sensitive changes."""


def generate_agents_md(
    project_purpose: str,
    project_rules: str,
    build_commands: str,
    test_commands: str,
    security_notes: str,
) -> str:
    purpose = project_purpose.strip() or "Describe what this project is for."
    rules = project_rules.strip() or DEFAULT_PROJECT_RULES
    build = build_commands.strip() or "Document build commands here after verifying they are safe to run."
    test = test_commands.strip() or "Document test commands here after verifying they are safe to run."
    security = security_notes.strip() or "Review scripts, installers, environment files, and generated code before execution."

    return f"""# AGENTS.md

## Project Purpose

{purpose}

## Rules for Codex

{rules}

## Build Commands

{build}

## Test Commands

{test}

## Security Notes

{security}

## Hard Safety Rules

{HARD_SAFETY_RULES}
"""
