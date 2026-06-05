from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
LIFECYCLE_SCRIPTS = {"preinstall", "install", "postinstall", "prepare", "prepublish"}
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
EXECUTABLE_EXTENSIONS = {
    ".bat": ("medium", "Batch script found. Review before running because it can execute commands on Windows."),
    ".cmd": ("medium", "Command script found. Review before running because it can execute commands on Windows."),
    ".ps1": ("high", "PowerShell script found. Review carefully before running."),
    ".sh": ("medium", "Shell script found. Review before running in a Unix-like shell."),
    ".exe": ("high", "Windows executable found. Do not run it unless you trust its origin."),
    ".dll": ("high", "Windows library file found. Review its origin before loading or executing related software."),
}
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__"}
MAX_TEXT_BYTES = 1024 * 1024

PATTERNS = {
    "Invoke-Expression": ("high", "PowerShell dynamic execution pattern found."),
    "iex": ("high", "PowerShell shorthand for Invoke-Expression found."),
    "curl": ("medium", "Network download command reference found."),
    "wget": ("medium", "Network download command reference found."),
    "Start-Process": ("high", "PowerShell process launch pattern found."),
    "encodedcommand": ("high", "Encoded PowerShell command pattern found."),
    "fromBase64String": ("high", "Base64 decoding pattern found."),
    "child_process": ("high", "Node.js process execution API reference found."),
    "eval(": ("high", "Dynamic code evaluation pattern found."),
}


def scan_project(project_path: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    for current_root, dirs, files in os.walk(project_path):
        dirs[:] = [name for name in dirs if name.lower() not in SKIP_DIRS]
        root_path = Path(current_root)

        for filename in files:
            file_path = root_path / filename
            relative_path = str(file_path.relative_to(project_path))
            lower_name = filename.lower()
            suffix = file_path.suffix.lower()

            if lower_name == "package.json":
                findings.extend(_scan_package_json(file_path, relative_path))

            if suffix in EXECUTABLE_EXTENSIONS:
                severity, explanation = EXECUTABLE_EXTENSIONS[suffix]
                findings.append(_finding(relative_path, "executable-or-script-file", severity, explanation))

            if lower_name == ".env":
                findings.append(
                    _finding(
                        relative_path,
                        "environment-file",
                        "high",
                        "Environment file found. Review for secrets before sharing or running tools.",
                    )
                )

            if lower_name in LOCKFILES:
                findings.append(
                    _finding(
                        relative_path,
                        "lockfile",
                        "low",
                        "Dependency lockfile found. Review dependency changes before installing.",
                    )
                )

            findings.extend(_scan_text_patterns(file_path, relative_path))

    return {"overall_risk": _overall_risk(findings), "findings": findings}


def _scan_package_json(file_path: Path, relative_path: str) -> list[dict[str, str]]:
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [
            _finding(
                relative_path,
                "package-json-read-error",
                "medium",
                "package.json could not be parsed. Review it manually before installing dependencies.",
            )
        ]

    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return []

    findings: list[dict[str, str]] = []
    for script_name in sorted(LIFECYCLE_SCRIPTS.intersection(scripts.keys())):
        findings.append(
            _finding(
                relative_path,
                "package-lifecycle-script",
                "high",
                f"package.json defines a '{script_name}' lifecycle script. Review it before installing dependencies.",
            )
        )
    return findings


def _scan_text_patterns(file_path: Path, relative_path: str) -> list[dict[str, str]]:
    try:
        if file_path.stat().st_size > MAX_TEXT_BYTES:
            return []
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    lower_text = text.lower()
    findings = []
    for pattern, (severity, explanation) in PATTERNS.items():
        needle = pattern.lower()
        if needle in lower_text:
            findings.append(_finding(relative_path, "suspicious-text-pattern", severity, f"{explanation} Pattern: {pattern}"))
    return findings


def _finding(path: str, finding_type: str, severity: str, explanation: str) -> dict[str, str]:
    return {
        "path": path,
        "type": finding_type,
        "severity": severity,
        "explanation": explanation,
    }


def _overall_risk(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "none"
    highest = max(RISK_ORDER[finding["severity"]] for finding in findings)
    for name, value in RISK_ORDER.items():
        if value == highest:
            return name
    return "none"
