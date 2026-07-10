from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.safety import (
    ensure_project_directory,
    is_reparse_point_or_symlink,
)


class ProjectPathSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        )
        self.base_path = Path(self.temporary_directory.name)
        self.workspace_root = self.base_path / "workspace"
        self.workspace_root.mkdir()
        self.project_path = self.workspace_root / "project"
        self.project_path.mkdir()
        self.outside_path = self.base_path / "outside"
        self.outside_path.mkdir()
        self.addCleanup(self.temporary_directory.cleanup)

    def assert_path_error(self, project_path: str, status_code: int) -> None:
        with self.assertRaises(HTTPException) as raised:
            ensure_project_directory(self.workspace_root, project_path)
        self.assertEqual(raised.exception.status_code, status_code)

    def create_directory_symlink(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Directory symlinks are unavailable: {exc}")

    def test_valid_contained_project_path_is_accepted(self) -> None:
        result = ensure_project_directory(
            self.workspace_root,
            str(self.project_path),
        )

        self.assertEqual(result, self.project_path.resolve())

    def test_relative_project_path_is_rejected(self) -> None:
        self.assert_path_error("project", 400)

    def test_forward_slash_traversal_is_rejected(self) -> None:
        traversal_path = f"{self.workspace_root}/project/../other"
        self.assert_path_error(traversal_path, 400)

    def test_windows_style_traversal_is_rejected(self) -> None:
        traversal_path = f"{self.workspace_root}\\project\\..\\other"
        self.assert_path_error(traversal_path, 400)

    def test_absolute_path_outside_workspace_is_rejected(self) -> None:
        self.assert_path_error(str(self.outside_path), 403)

    def test_malformed_path_is_rejected(self) -> None:
        self.assert_path_error(f"{self.workspace_root}\0malformed", 400)

    def test_directory_symlink_escape_is_rejected(self) -> None:
        linked_project = self.workspace_root / "linked-project"
        self.create_directory_symlink(linked_project, self.outside_path)

        self.assert_path_error(str(linked_project), 403)

    def test_reported_reparse_component_is_rejected(self) -> None:
        alias_path = self.workspace_root / "junction-alias"
        alias_path.mkdir()

        def is_reparse(path: Path) -> bool:
            return path == alias_path

        with patch(
            "app.safety.is_reparse_point_or_symlink",
            side_effect=is_reparse,
        ):
            self.assert_path_error(str(alias_path), 403)


class ReparseDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path("detector-test-path")

    def test_is_symlink_returns_true(self) -> None:
        with (
            patch.object(Path, "is_symlink", return_value=True),
            patch.object(
                Path,
                "is_junction",
                create=True,
            ) as is_junction,
            patch.object(Path, "stat") as stat,
        ):
            result = is_reparse_point_or_symlink(self.path)

        self.assertTrue(result)
        is_junction.assert_not_called()
        stat.assert_not_called()

    def test_is_junction_returns_true(self) -> None:
        with (
            patch.object(Path, "is_symlink", return_value=False),
            patch.object(
                Path,
                "is_junction",
                return_value=True,
                create=True,
            ),
            patch.object(Path, "stat") as stat,
        ):
            result = is_reparse_point_or_symlink(self.path)

        self.assertTrue(result)
        stat.assert_not_called()

    def test_windows_reparse_attribute_returns_true(self) -> None:
        file_stat = SimpleNamespace(st_file_attributes=0x400)
        with (
            patch.object(Path, "is_symlink", return_value=False),
            patch.object(
                Path,
                "is_junction",
                return_value=False,
                create=True,
            ),
            patch.object(Path, "stat", return_value=file_stat) as stat,
        ):
            result = is_reparse_point_or_symlink(self.path)

        self.assertTrue(result)
        stat.assert_called_once_with(follow_symlinks=False)

    def test_ordinary_file_returns_false(self) -> None:
        file_stat = SimpleNamespace(st_file_attributes=0)
        with (
            patch.object(Path, "is_symlink", return_value=False),
            patch.object(
                Path,
                "is_junction",
                return_value=False,
                create=True,
            ),
            patch.object(Path, "stat", return_value=file_stat) as stat,
        ):
            result = is_reparse_point_or_symlink(self.path)

        self.assertFalse(result)
        stat.assert_called_once_with(follow_symlinks=False)


if __name__ == "__main__":
    unittest.main()
