from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException


SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9._ -]+")


def sanitize_folder_name(name: str) -> str:
    cleaned = SAFE_NAME_PATTERN.sub("-", name).strip(" .-_")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace(" ", "-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Project name must contain usable characters.")
    return cleaned[:80]


def configured_root(root_value: str) -> Path:
    root = Path(root_value).expanduser()
    if not root.is_absolute():
        raise HTTPException(status_code=400, detail="Workspace root must be an absolute path.")
    return root.resolve()


def ensure_inside_root(workspace_root: Path, candidate: str | Path) -> Path:
    path = Path(candidate).expanduser()
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Path is outside the configured workspace root.") from exc
    return resolved


def ensure_project_directory(workspace_root: Path, project_path: str) -> Path:
    resolved = ensure_inside_root(workspace_root, project_path)
    if resolved == workspace_root:
        raise HTTPException(status_code=400, detail="Select a project folder inside the workspace root.")
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(status_code=404, detail="Project folder was not found.")
    return resolved
