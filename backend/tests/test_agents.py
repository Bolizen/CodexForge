from __future__ import annotations

import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import agents_write, main, safety
from app.schemas import AgentPreviewRequest


class AgentsWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        )
        self.base_path = Path(self.temporary_directory.name)
        self.workspace_root = self.base_path / "workspace"
        self.workspace_root.mkdir()
        self.project_path = self.workspace_root / "project"
        self.project_path.mkdir()
        self.addCleanup(self.temporary_directory.cleanup)

    def payload(self, *, overwrite: bool = False) -> AgentPreviewRequest:
        return AgentPreviewRequest(
            project_path=str(self.project_path),
            project_purpose="Test project",
            overwrite=overwrite,
        )

    def write_agents(self, *, overwrite: bool = False) -> dict[str, object]:
        with (
            patch.object(
                main,
                "_ensure_project",
                return_value=self.project_path,
            ),
            patch.object(
                main,
                "_project_root",
                return_value=self.workspace_root,
            ),
        ):
            return main.write_agents(self.payload(overwrite=overwrite))

    def temporary_files(self) -> list[Path]:
        return list(self.project_path.glob(".codexforge-AGENTS.md-*.tmp"))

    def test_creates_literal_agents_file_when_absent(self) -> None:
        result = self.write_agents()
        agents_path = self.project_path / "AGENTS.md"

        self.assertTrue(result["written"])
        self.assertFalse(result["confirmation_required"])
        self.assertEqual(result["path"], str(agents_path))
        self.assertTrue(agents_path.is_file())
        self.assertIn("Test project", agents_path.read_text(encoding="utf-8"))
        self.assertEqual(agents_path.read_text(encoding="utf-8"), result["content"])
        self.assertEqual(self.temporary_files(), [])

    def test_create_target_is_not_visible_while_content_is_written(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        observer_path = self.workspace_root / "observed-hardlink.md"
        real_write = os.write
        link_attempted = False

        def write_chunk(file_descriptor: int, data: object) -> int:
            nonlocal link_attempted
            link_attempted = True
            with self.assertRaises(FileNotFoundError):
                os.link(agents_path, observer_path)
            return real_write(file_descriptor, data)

        with patch.object(agents_write.os, "write", side_effect=write_chunk):
            result = self.write_agents()

        self.assertTrue(link_attempted)
        self.assertTrue(result["written"])
        self.assertFalse(observer_path.exists())
        self.assertEqual(agents_path.read_text(encoding="utf-8"), result["content"])
        self.assertEqual(self.temporary_files(), [])

    def test_existing_file_requires_overwrite_confirmation(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        agents_path.write_text("original", encoding="utf-8")

        result = self.write_agents()

        self.assertFalse(result["written"])
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(agents_path.read_text(encoding="utf-8"), "original")

    def test_collision_during_atomic_create_requires_confirmation(self) -> None:
        agents_path = self.project_path / "AGENTS.md"

        def create_collision(project: Path, target: Path) -> None:
            target.write_text("collision", encoding="utf-8")

        with patch.object(
            agents_write,
            "_before_create",
            side_effect=create_collision,
        ):
            result = self.write_agents()

        self.assertFalse(result["written"])
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(agents_path.read_text(encoding="utf-8"), "collision")
        self.assertEqual(self.temporary_files(), [])

    def test_unsafe_create_collision_is_rejected_not_confirmed(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        unsafe = {"active": False}
        real_detector = safety.is_reparse_point_or_symlink

        def detect(path: Path, **kwargs: object) -> bool:
            if unsafe["active"] and path == agents_path:
                return True
            return real_detector(path, **kwargs)

        def collide(*args: object) -> int:
            unsafe["active"] = True
            raise FileExistsError

        with (
            patch.object(
                safety,
                "is_reparse_point_or_symlink",
                side_effect=detect,
            ),
            patch.object(
                agents_write,
                "_link_file",
                side_effect=collide,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                self.write_agents()

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(agents_path.exists())
        self.assertEqual(self.temporary_files(), [])

    def test_confirmed_overwrite_replaces_regular_file(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        agents_path.write_text("original", encoding="utf-8")
        old_status = agents_path.stat()
        old_identity = (old_status.st_dev, old_status.st_ino)

        result = self.write_agents(overwrite=True)

        self.assertTrue(result["written"])
        self.assertFalse(result["confirmation_required"])
        self.assertEqual(
            agents_path.read_text(encoding="utf-8"),
            result["content"],
        )
        new_status = agents_path.stat()
        self.assertNotEqual(
            old_identity,
            (new_status.st_dev, new_status.st_ino),
        )
        self.assertEqual(self.temporary_files(), [])

    def test_simulated_linked_or_reparse_target_is_rejected(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        agents_path.write_text("do not change", encoding="utf-8")

        with patch(
            "app.safety.is_reparse_point_or_symlink",
            side_effect=lambda path, **kwargs: path == agents_path,
        ):
            with self.assertRaises(HTTPException) as raised:
                self.write_agents(overwrite=True)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(
            agents_path.read_text(encoding="utf-8"),
            "do not change",
        )

    def test_reparse_inspection_error_is_rejected(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        agents_path.write_text("do not change", encoding="utf-8")

        with patch.object(
            Path,
            "is_symlink",
            side_effect=OSError("inspection failed"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self.write_agents(overwrite=True)

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(raised.exception.detail, "AGENTS.md path inspection failed.")
        self.assertEqual(
            agents_path.read_text(encoding="utf-8"),
            "do not change",
        )

    def test_parent_becoming_unsafe_before_replace_is_rejected(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        agents_path.write_text("original", encoding="utf-8")
        unsafe = {"active": False}
        real_detector = safety.is_reparse_point_or_symlink

        def detect(path: Path, **kwargs: object) -> bool:
            if unsafe["active"] and path == self.project_path:
                return True
            return real_detector(path, **kwargs)

        def make_parent_unsafe(*args: object) -> None:
            unsafe["active"] = True

        with (
            patch.object(
                safety,
                "is_reparse_point_or_symlink",
                side_effect=detect,
            ),
            patch.object(
                agents_write,
                "_before_replace",
                side_effect=make_parent_unsafe,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                self.write_agents(overwrite=True)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(agents_path.read_text(encoding="utf-8"), "original")
        self.assertEqual(self.temporary_files(), [])

    def test_target_becoming_unsafe_before_replace_is_rejected(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        agents_path.write_text("original", encoding="utf-8")
        unsafe = {"active": False}
        real_detector = safety.is_reparse_point_or_symlink

        def detect(path: Path, **kwargs: object) -> bool:
            if unsafe["active"] and path == agents_path:
                return True
            return real_detector(path, **kwargs)

        def make_target_unsafe(*args: object) -> None:
            unsafe["active"] = True

        with (
            patch.object(
                safety,
                "is_reparse_point_or_symlink",
                side_effect=detect,
            ),
            patch.object(
                agents_write,
                "_before_replace",
                side_effect=make_target_unsafe,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                self.write_agents(overwrite=True)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(agents_path.read_text(encoding="utf-8"), "original")
        self.assertEqual(self.temporary_files(), [])

    def test_replace_failure_removes_temporary_file(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        agents_path.write_text("original", encoding="utf-8")

        with patch.object(
            agents_write.os,
            "replace",
            side_effect=PermissionError(errno.EACCES, "private replace detail"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self.write_agents(overwrite=True)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(agents_path.read_text(encoding="utf-8"), "original")
        self.assertEqual(self.temporary_files(), [])

    def test_enospc_replace_failure_returns_generic_server_error(self) -> None:
        agents_path = self.project_path / "AGENTS.md"
        agents_path.write_text("original", encoding="utf-8")

        with patch.object(
            agents_write.os,
            "replace",
            side_effect=OSError(errno.ENOSPC, "private disk detail"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self.write_agents(overwrite=True)

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(raised.exception.detail, "AGENTS.md could not be written.")
        self.assertNotIn("private", raised.exception.detail)
        self.assertEqual(agents_path.read_text(encoding="utf-8"), "original")
        self.assertEqual(self.temporary_files(), [])

    def test_fsync_failure_returns_generic_server_error_and_cleans_temporary(self) -> None:
        agents_path = self.project_path / "AGENTS.md"

        with patch.object(
            agents_write.os,
            "fsync",
            side_effect=OSError(errno.EIO, "private fsync detail"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self.write_agents()

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(
            raised.exception.detail,
            "AGENTS.md content could not be persisted.",
        )
        self.assertNotIn("private", raised.exception.detail)
        self.assertFalse(agents_path.exists())
        self.assertEqual(self.temporary_files(), [])

    def test_hardlinked_target_is_rejected_without_changing_other_name(self) -> None:
        outside_path = self.workspace_root / "outside-agents.md"
        outside_path.write_text("do not change", encoding="utf-8")
        agents_path = self.project_path / "AGENTS.md"
        try:
            os.link(outside_path, agents_path)
        except OSError as exc:
            self.skipTest(f"Hardlinks are unavailable: {exc}")

        with self.assertRaises(HTTPException) as raised:
            self.write_agents(overwrite=True)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            outside_path.read_text(encoding="utf-8"),
            "do not change",
        )

    def test_non_regular_target_is_rejected(self) -> None:
        (self.project_path / "AGENTS.md").mkdir()

        with self.assertRaises(HTTPException) as raised:
            self.write_agents(overwrite=True)

        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
