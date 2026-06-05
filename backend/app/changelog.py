from __future__ import annotations

CHANGELOG_ENTRIES = [
    {
        "version": "0.06",
        "title": "Bugfix pass",
        "changes": [
            "Case-insensitive scanner skip directories.",
            "Scan history finding normalization.",
            "Frontend stale selected project cleanup.",
            "Unexpected severity tolerance.",
        ],
    },
    {
        "version": "0.05",
        "title": "AGENTS.md end-to-end review/manual test notes",
        "changes": [
            "Reviewed AGENTS.md preview and write flow.",
            "Added manual test notes for project creation, AGENTS.md generation, overwrite behavior, and scanning.",
        ],
    },
    {
        "version": "0.04",
        "title": r"Workspace root correction to C:\CodeProjects",
        "changes": [
            r"Changed the default workspace root to C:\CodeProjects.",
            "Validated selected projects under the configured workspace root.",
        ],
    },
    {
        "version": "0.03",
        "title": "AGENTS.md generator",
        "changes": [
            "Added AGENTS.md preview and write endpoints.",
            "Added frontend form with overwrite confirmation.",
        ],
    },
    {
        "version": "0.02",
        "title": "Scanner implementation",
        "changes": [
            "Added read-only project risk scanning.",
            "Added scan report display and scan history storage.",
        ],
    },
    {
        "version": "0.01",
        "title": "MVP scaffold",
        "changes": [
            "Added FastAPI backend, React/Vite frontend, and SQLite storage.",
            "Added local project dashboard and project creation flow.",
        ],
    },
]
