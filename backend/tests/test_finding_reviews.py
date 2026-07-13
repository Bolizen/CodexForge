from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import database, main
from app.finding_reviews import enrich_scan, finding_fingerprint, review_summary, valid_fingerprint
from app.schemas import FindingReviewDelete, FindingReviewRequest, ProjectPathRequest


class FindingFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_deterministic_and_excludes_display_wording(self) -> None:
        finding = {
            "type": "suspicious-text-pattern",
            "path": "tests/sample.py",
            "severity": "high",
            "pattern": "eval(",
            "explanation": "First display explanation.",
            "action": "First display action.",
        }
        fingerprint = finding_fingerprint(finding)
        reordered = {
            "action": "Changed display action.",
            "explanation": "Changed display explanation.",
            "pattern": "eval(",
            "severity": "high",
            "path": "tests\\sample.py",
            "type": "suspicious-text-pattern",
        }
        self.assertEqual(fingerprint, finding_fingerprint(reordered))
        self.assertRegex(fingerprint, r"^cf1_[0-9a-f]{64}$")
        self.assertNotIn("eval", fingerprint)

    def test_nested_order_missing_values_and_repeated_reads_are_stable(self) -> None:
        first = {
            "type": "dependency-source-anomaly",
            "path": "locks/package-lock.json",
            "severity": "medium",
            "metadata": {"source": "registry.example", "optional": None, "flags": ["direct", None, ""]},
        }
        second = {
            "metadata": {"flags": ["direct"], "source": "registry.example"},
            "severity": "medium",
            "path": "locks\\package-lock.json",
            "type": "dependency-source-anomaly",
        }
        fingerprint = finding_fingerprint(first)
        self.assertEqual(fingerprint, finding_fingerprint(first))
        self.assertEqual(fingerprint, finding_fingerprint(second))

    def test_paths_are_relative_case_sensitive_and_severity_requires_review(self) -> None:
        base = {"type": "hardlink", "path": "Tests/Fixture.py", "severity": "high"}
        self.assertEqual(finding_fingerprint(base), finding_fingerprint({**base, "path": "Tests\\Fixture.py"}))
        self.assertNotEqual(finding_fingerprint(base), finding_fingerprint({**base, "path": "tests/Fixture.py"}))
        self.assertNotEqual(finding_fingerprint(base), finding_fingerprint({**base, "severity": "medium"}))
        for path in ("../outside.py", "inside/../../outside.py", "/host/file.py", "C:\\host\\file.py", "\\\\server\\share\\file.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                finding_fingerprint({**base, "path": path})

        unsafe = enrich_scan({"findings": [{**base, "path": "../outside.py"}]}, [])
        self.assertIsNone(unsafe["findings"][0]["fingerprint"])
        self.assertIsNone(unsafe["findings"][0]["review"])
        self.assertEqual(unsafe["reviewSummary"]["unreviewedFindingCount"], 1)

    def test_version_and_identity_fields_cannot_cross_match(self) -> None:
        base = {"type": "dependency-source-changed", "path": "package-lock.json", "severity": "medium"}
        fingerprint = finding_fingerprint({
            **base,
            "script": "postinstall",
            "operation": "compare-lockfile",
            "ecosystem": "node",
            "package": "example",
            "dependencyGroup": "dependencies",
            "sourceType": "registry",
            "sourceIdentifier": "registry.example",
        })
        for field, value in (
            ("script", "prepare"),
            ("operation", "inspect-lockfile"),
            ("ecosystem", "python"),
            ("package", "other"),
            ("dependencyGroup", "devDependencies"),
            ("sourceType", "url"),
            ("sourceIdentifier", "other.example"),
        ):
            changed = {
                **base,
                "script": "postinstall",
                "operation": "compare-lockfile",
                "ecosystem": "node",
                "package": "example",
                "dependencyGroup": "dependencies",
                "sourceType": "registry",
                "sourceIdentifier": "registry.example",
                field: value,
            }
            self.assertNotEqual(fingerprint, finding_fingerprint(changed), field)

        self.assertFalse(valid_fingerprint("cf2_" + "a" * 64))

    def test_risk_summary_is_defensive_and_never_hides_an_unreviewed_high(self) -> None:
        reviewed = {"severity": "high", "review": {"status": "expected"}}
        unreviewed = {"severity": "high", "review": None}
        self.assertEqual(review_summary([])["highestUnreviewedSeverity"], "none")
        self.assertEqual(review_summary([reviewed])["highestUnreviewedSeverity"], "none")
        partial = review_summary([reviewed, unreviewed])
        self.assertEqual(partial["reviewedFindingCount"], 1)
        self.assertEqual(partial["unreviewedFindingCount"], 1)
        self.assertEqual(partial["highestUnreviewedSeverity"], "high")
        self.assertEqual(review_summary([{"severity": "unexpected", "review": None}])["highestUnreviewedSeverity"], "high")

    def test_changed_path_type_pattern_or_evidence_does_not_match(self) -> None:
        base = {"type": "suspicious-text-pattern", "path": "tests/sample.py", "severity": "high", "pattern": "eval("}
        fingerprint = finding_fingerprint(base)
        variants = [
            {**base, "path": "tests/other.py"},
            {**base, "type": "executable-or-script-file"},
            {**base, "pattern": "child_process"},
            {**base, "metadata": {"line": 8}},
        ]
        self.assertTrue(all(finding_fingerprint(variant) != fingerprint for variant in variants))

    def test_legacy_pattern_wording_retains_exact_pattern_identity(self) -> None:
        first = {"type": "suspicious-text-pattern", "path": "test.py", "severity": "high", "explanation": "Dynamic code. Pattern: eval("}
        second = {**first, "explanation": "Process API. Pattern: child_process"}
        self.assertNotEqual(finding_fingerprint(first), finding_fingerprint(second))


class FindingReviewApiTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.database_path = self.base / "codexforge.db"
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.other = self.root / "other"
        self.other.mkdir()
        for active_patch in (
            patch.object(database, "DB_PATH", self.database_path),
            patch.object(database, "get_connection", side_effect=self.closing_connection),
            patch.object(main, "get_connection", side_effect=self.closing_connection),
        ):
            active_patch.start()
            self.addCleanup(active_patch.stop)
        database.init_db()
        database.set_setting(database.WORKSPACE_ROOT_SETTING, str(self.root))
        self.register(self.project)
        self.register(self.other)

    @contextmanager
    def closing_connection(self) -> object:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def register(self, project: Path) -> None:
        with database.get_connection() as connection:
            connection.execute(
                "INSERT INTO projects (path, name, created_at) VALUES (?, ?, ?)",
                (str(project), project.name, "2026-01-01T00:00:00+00:00"),
            )

    def scan_pattern(self, project: Path, pattern: str = "eval(") -> dict[str, object]:
        (project / "fixture.py").write_text(f"value = '{pattern}'\n", encoding="utf-8")
        return main.run_scan(ProjectPathRequest(project_path=str(project)))

    def test_create_update_reopen_and_raw_persistence(self) -> None:
        scanned = self.scan_pattern(self.project)
        finding = next(item for item in scanned["findings"] if item["type"] == "suspicious-text-pattern")
        fingerprint = finding["fingerprint"]
        self.assertIsNone(finding["review"])
        self.assertEqual(scanned["overall_risk"], "high")
        self.assertEqual(scanned["reviewSummary"]["highestUnreviewedSeverity"], "high")

        with database.get_connection() as connection:
            raw = json.loads(connection.execute("SELECT findings_json FROM scans WHERE id = ?", (scanned["id"],)).fetchone()["findings_json"])
        self.assertNotIn("fingerprint", raw[0])
        self.assertNotIn("review", raw[0])

        created = main.update_finding_review(FindingReviewRequest(
            project_path=str(self.project), fingerprint=fingerprint, status="expected", note="Known regression fixture.",
        ))["review"]
        self.assertEqual(created["status"], "expected")
        self.assertEqual(created["note"], "Known regression fixture.")

        updated = main.update_finding_review(FindingReviewRequest(
            project_path=str(self.project), fingerprint=fingerprint, status="reviewed", note="Reviewed again.",
        ))["review"]
        self.assertEqual(updated["created_at"], created["created_at"])
        self.assertEqual(updated["status"], "reviewed")
        self.assertEqual(main.list_finding_reviews(str(self.project))["reviews"][0]["note"], "Reviewed again.")

        history = main.scan_history(str(self.project))["scans"][0]
        self.assertEqual(history["overall_risk"], "high")
        self.assertEqual(history["reviewSummary"]["reviewedFindingCount"], 1)
        self.assertEqual(history["reviewSummary"]["highestUnreviewedSeverity"], "none")
        self.assertEqual(history["findings"][0]["review"]["note"], "Reviewed again.")

        repeated = self.scan_pattern(self.project)
        repeated_finding = next(item for item in repeated["findings"] if item["fingerprint"] == fingerprint)
        self.assertEqual(repeated_finding["review"]["status"], "reviewed")

        reopened = main.delete_finding_review(FindingReviewDelete(project_path=str(self.project), fingerprint=fingerprint))
        self.assertTrue(reopened["reopened"])
        self.assertIsNone(main.scan_history(str(self.project))["scans"][0]["findings"][0]["review"])
        repeated_reopen = main.delete_finding_review(FindingReviewDelete(project_path=str(self.project), fingerprint=fingerprint))
        self.assertTrue(repeated_reopen["reopened"])

    def test_project_isolation_and_changed_finding_are_unreviewed(self) -> None:
        first = self.scan_pattern(self.project)
        fingerprint = first["findings"][0]["fingerprint"]
        main.update_finding_review(FindingReviewRequest(
            project_path=str(self.project), fingerprint=fingerprint, status="expected", note="Expected here only.",
        ))
        other_scan = self.scan_pattern(self.other)
        self.assertEqual(other_scan["findings"][0]["fingerprint"], fingerprint)
        self.assertIsNone(other_scan["findings"][0]["review"])
        self.assertEqual(main.list_finding_reviews(str(self.other))["reviews"], [])

        changed = self.scan_pattern(self.project, "child_process")
        changed_finding = next(item for item in changed["findings"] if item["type"] == "suspicious-text-pattern")
        self.assertNotEqual(changed_finding["fingerprint"], fingerprint)
        self.assertIsNone(changed_finding["review"])
        self.assertEqual(changed["reviewSummary"]["highestUnreviewedSeverity"], "high")

    def test_validation_and_unknown_fingerprints_fail_closed(self) -> None:
        self.scan_pattern(self.project)
        with self.assertRaises(ValidationError):
            FindingReviewRequest(project_path=str(self.project), fingerprint="invalid", status="reviewed", note="")
        with self.assertRaises(ValidationError):
            FindingReviewRequest(project_path=str(self.project), fingerprint="cf1_" + "a" * 64, status="invalid", note="")
        with self.assertRaises(ValidationError):
            FindingReviewRequest(project_path=str(self.project), fingerprint="cf1_" + "a" * 64, status="reviewed", note="x" * 1001)
        with self.assertRaises(HTTPException) as context:
            main.update_finding_review(FindingReviewRequest(
                project_path=str(self.project), fingerprint="cf1_" + "a" * 64, status="reviewed", note="",
            ))
        self.assertEqual(context.exception.status_code, 404)

        unknown = "cf1_" + "b" * 64
        self.assertTrue(main.delete_finding_review(FindingReviewDelete(
            project_path=str(self.project), fingerprint=unknown,
        ))["reopened"])
        with database.get_connection() as connection:
            connection.execute(
                "INSERT INTO finding_reviews (project_path, fingerprint, status, note, created_at, updated_at) "
                "VALUES (?, ?, 'reviewed', '', 'now', 'now')",
                (str(self.project), unknown),
            )
        history = main.scan_history(str(self.project))["scans"][0]
        self.assertEqual(history["reviewSummary"]["reviewedFindingCount"], 0)

    def test_unregister_removes_reviews_without_touching_project_files(self) -> None:
        scanned = self.scan_pattern(self.project)
        fingerprint = scanned["findings"][0]["fingerprint"]
        main.update_finding_review(FindingReviewRequest(
            project_path=str(self.project), fingerprint=fingerprint, status="expected", note="fixture",
        ))
        fixture = self.project / "fixture.py"
        main.unregister_project(ProjectPathRequest(project_path=str(self.project)))
        self.assertTrue(fixture.is_file())
        with database.get_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM finding_reviews WHERE project_path = ?", (str(self.project),),
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_legacy_scan_is_enriched_without_rewriting_stored_evidence(self) -> None:
        legacy_finding = {
            "file_path": "legacy.py",
            "finding_type": "suspicious-text-pattern",
            "severity": "high",
            "explanation": "Legacy evidence. Pattern: eval(",
        }
        with database.get_connection() as connection:
            connection.execute(
                "INSERT INTO scans (project_path, scan_date, overall_risk, findings_json) VALUES (?, ?, ?, ?)",
                (str(self.project), "legacy", "high", json.dumps([legacy_finding])),
            )
        history = main.scan_history(str(self.project))["scans"][0]
        self.assertRegex(history["findings"][0]["fingerprint"], r"^cf1_[0-9a-f]{64}$")
        self.assertIsNone(history["findings"][0]["review"])
        with database.get_connection() as connection:
            stored = json.loads(connection.execute("SELECT findings_json FROM scans WHERE scan_date = 'legacy'").fetchone()["findings_json"])
        self.assertEqual(stored, [legacy_finding])


if __name__ == "__main__":
    unittest.main()
