from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "codexforge.db"
DEFAULT_WORKSPACE_ROOT = r"C:\CodeProjects"
LEGACY_DEFAULT_PROJECT_ROOT = r"C:\Code Projects"
WORKSPACE_ROOT_SETTING = "project_root"


def get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                path TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                project_type TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                scan_date TEXT NOT NULL,
                overall_risk TEXT NOT NULL,
                findings_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (WORKSPACE_ROOT_SETTING, DEFAULT_WORKSPACE_ROOT),
        )
        connection.execute(
            "UPDATE settings SET value = ? WHERE key = ? AND value = ?",
            (DEFAULT_WORKSPACE_ROOT, WORKSPACE_ROOT_SETTING, LEGACY_DEFAULT_PROJECT_ROOT),
        )


def get_setting(key: str) -> str | None:
    with get_connection() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def latest_scan_map() -> dict[str, sqlite3.Row]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT s.*
            FROM scans s
            JOIN (
                SELECT project_path, MAX(scan_date) AS scan_date
                FROM scans
                GROUP BY project_path
            ) latest
            ON latest.project_path = s.project_path AND latest.scan_date = s.scan_date
            """
        ).fetchall()
        return {row["project_path"]: row for row in rows}


def note_counts() -> dict[str, int]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT project_path, COUNT(*) AS note_count FROM notes GROUP BY project_path"
        ).fetchall()
        return {row["project_path"]: row["note_count"] for row in rows}


def row_to_scan(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_path": row["project_path"],
        "scan_date": row["scan_date"],
        "overall_risk": row["overall_risk"],
        "findings": [_normalize_finding(finding) for finding in json.loads(row["findings_json"])],
    }


def _normalize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": finding.get("path") or finding.get("file_path") or "",
        "type": finding.get("type") or finding.get("finding_type") or "unknown",
        "severity": finding.get("severity") or "low",
        "explanation": finding.get("explanation") or "Review this finding manually.",
    }
