from __future__ import annotations

import errno
import os
import secrets
import stat
from pathlib import Path

from fastapi import HTTPException

from . import safety


_FILE_MODE = 0o600
_TEMP_ATTEMPTS = 32
_USE_DIRECTORY_FD = all(
    function in os.supports_dir_fd
    for function in (os.open, os.stat, os.unlink, os.replace)
)
_FILESYSTEM_CONFLICT_ERRNOS = {
    errno.EACCES,
    errno.EBUSY,
    errno.EEXIST,
    errno.EISDIR,
    errno.ELOOP,
    errno.ENOTDIR,
    errno.ENOTEMPTY,
    errno.EPERM,
    errno.EROFS,
    errno.EXDEV,
}


def filesystem_error_status(error: OSError) -> int:
    """Map expected filesystem conflicts to 409 and server I/O failures to 500."""
    return 409 if error.errno in _FILESYSTEM_CONFLICT_ERRNOS else 500


def _filesystem_http_exception(
    error: OSError,
    *,
    conflict_detail: str,
    server_detail: str,
) -> HTTPException:
    status_code = filesystem_error_status(error)
    detail = conflict_detail if status_code == 409 else server_detail
    return HTTPException(status_code=status_code, detail=detail)


def _path_is_linked(path: Path, label: str) -> bool:
    try:
        return safety.is_reparse_point_or_symlink(path, raise_on_error=True)
    except OSError as exc:
        raise _filesystem_http_exception(
            exc,
            conflict_detail=f"{label} could not be safely inspected.",
            server_detail="AGENTS.md path inspection failed.",
        ) from exc


def safe_write_project_file(
    workspace_root: Path,
    project_directory: Path,
    target_filename: str,
    content: str,
    *,
    overwrite: bool,
) -> Path:
    project = Path(project_directory)
    target = _literal_target(project, target_filename)
    _validate_write_context(workspace_root, project, target)

    directory_fd, directory_status = _open_project_directory(project)
    try:
        if overwrite:
            _atomic_overwrite(
                workspace_root,
                project,
                target,
                content,
                directory_fd,
                directory_status,
            )
        else:
            _exclusive_create(
                workspace_root,
                project,
                target,
                content,
                directory_fd,
                directory_status,
            )
    finally:
        if directory_fd is not None:
            _close_descriptor(directory_fd)

    return target


def _exclusive_create(
    workspace_root: Path,
    project: Path,
    target: Path,
    content: str,
    directory_fd: int | None,
    directory_status: os.stat_result | None,
) -> None:
    _validate_write_context(workspace_root, project, target)
    _validate_directory_identity(project, directory_fd, directory_status)
    if _inspect_regular_file(target, allow_missing=True, label="AGENTS.md target") is not None:
        raise FileExistsError(errno.EEXIST, "AGENTS.md already exists.", target)

    temporary_name, temporary_identity = _prepare_temporary_file(
        directory_fd,
        project,
        target,
        content,
    )
    temporary_path = project / temporary_name
    published = False
    temporary_removed = False

    try:
        _before_create(project, target)
        _validate_write_context(workspace_root, project, target)
        _validate_directory_identity(project, directory_fd, directory_status)
        _inspect_regular_file(target, allow_missing=True, label="AGENTS.md target")
        temporary_status = _inspect_regular_file(
            temporary_path,
            allow_missing=False,
            label="Temporary AGENTS.md",
        )
        if temporary_status is None or _identity(temporary_status) != temporary_identity:
            raise HTTPException(status_code=409, detail="Temporary AGENTS.md was redirected before publication.")

        try:
            _link_file(directory_fd, project, temporary_name, target.name)
        except FileExistsError:
            _validate_write_context(workspace_root, project, target)
            _validate_directory_identity(project, directory_fd, directory_status)
            raise
        published = True

        _unlink_owned_file(directory_fd, project, temporary_name, temporary_identity)
        temporary_removed = True
        target_status = _inspect_regular_file(target, allow_missing=False, label="AGENTS.md target")
        if target_status is None or _identity(target_status) != temporary_identity:
            raise HTTPException(status_code=409, detail="New AGENTS.md was redirected during publication.")
    except BaseException:
        if published:
            _cleanup_created_file(
                directory_fd,
                project,
                target.name,
                temporary_identity,
            )
        raise
    finally:
        if not temporary_removed:
            _cleanup_created_file(
                directory_fd,
                project,
                temporary_name,
                temporary_identity,
            )


def _atomic_overwrite(
    workspace_root: Path,
    project: Path,
    target: Path,
    content: str,
    directory_fd: int | None,
    directory_status: os.stat_result | None,
) -> None:
    temporary_name, temporary_identity = _prepare_temporary_file(
        directory_fd,
        project,
        target,
        content,
    )
    replaced = False

    try:
        temporary_path = project / temporary_name
        _before_replace(project, target, temporary_path)
        _validate_write_context(workspace_root, project, target)
        _validate_directory_identity(project, directory_fd, directory_status)
        _inspect_regular_file(target, allow_missing=True, label="AGENTS.md target")

        temporary_status = _inspect_regular_file(
            temporary_path,
            allow_missing=False,
            label="Temporary AGENTS.md",
        )
        if temporary_status is None or _identity(temporary_status) != temporary_identity:
            raise HTTPException(status_code=409, detail="Temporary AGENTS.md was redirected before replacement.")

        _replace_file(directory_fd, project, temporary_name, target.name)
        replaced = True
    finally:
        if not replaced:
            _cleanup_created_file(
                directory_fd,
                project,
                temporary_name,
                temporary_identity,
            )


def _prepare_temporary_file(
    directory_fd: int | None,
    project: Path,
    target: Path,
    content: str,
) -> tuple[str, tuple[int, int]]:
    temporary_name, file_descriptor = _create_temporary_file(directory_fd, project, target.name)
    temporary_identity: tuple[int, int] | None = None
    try:
        opened_status = _descriptor_status(file_descriptor, "Temporary AGENTS.md")
        temporary_identity = _identity(opened_status)
        _require_safe_file_status(opened_status, "Temporary AGENTS.md")
        _write_and_sync(file_descriptor, content)
        final_status = _validate_open_file(file_descriptor, "Temporary AGENTS.md")
        if _identity(final_status) != temporary_identity:
            raise HTTPException(status_code=409, detail="Temporary AGENTS.md changed while it was being written.")
        os.close(file_descriptor)
        file_descriptor = -1
        return temporary_name, temporary_identity
    except BaseException:
        if file_descriptor >= 0:
            _close_descriptor(file_descriptor)
        _cleanup_created_file(directory_fd, project, temporary_name, temporary_identity)
        raise


def _validate_write_context(
    workspace_root: Path,
    project: Path,
    target: Path,
) -> None:
    workspace_root = Path(workspace_root)
    if not workspace_root.is_absolute() or not project.is_absolute() or not target.is_absolute():
        raise HTTPException(status_code=400, detail="Safe project writes require absolute paths.")

    _inspect_directory(workspace_root, "Workspace root")
    validated_project = safety.ensure_project_directory(
        workspace_root,
        str(project),
        raise_on_inspection_error=True,
    )
    if validated_project != project:
        raise HTTPException(status_code=403, detail="Selected project directory was redirected.")

    validated_target = safety.ensure_inside_root(
        workspace_root,
        target,
        raise_on_inspection_error=True,
    )
    try:
        target.relative_to(project)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="AGENTS.md target is outside the selected project folder.") from exc
    if validated_target != target:
        raise HTTPException(status_code=403, detail="AGENTS.md target was redirected.")

    _inspect_directory(project, "Selected project directory")
    _inspect_regular_file(target, allow_missing=True, label="AGENTS.md target")


def _literal_target(project: Path, target_filename: str) -> Path:
    if (
        not target_filename
        or target_filename in {".", ".."}
        or "/" in target_filename
        or "\\" in target_filename
        or ":" in target_filename
        or "\0" in target_filename
    ):
        raise HTTPException(status_code=403, detail="AGENTS.md target filename is invalid.")
    return project / target_filename


def _inspect_directory(path: Path, label: str) -> os.stat_result:
    if _path_is_linked(path, label):
        raise HTTPException(status_code=403, detail=f"{label} is a symlink, junction, or reparse point.")
    try:
        path_status = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise _filesystem_http_exception(
            exc,
            conflict_detail=f"{label} could not be safely inspected.",
            server_detail="AGENTS.md path inspection failed.",
        ) from exc
    if not stat.S_ISDIR(path_status.st_mode):
        raise HTTPException(status_code=409, detail=f"{label} is not a directory.")
    return path_status


def _inspect_regular_file(
    path: Path,
    *,
    allow_missing: bool,
    label: str,
) -> os.stat_result | None:
    if _path_is_linked(path, label):
        raise HTTPException(status_code=403, detail=f"{label} is a symlink, junction, or reparse point.")
    try:
        path_status = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise HTTPException(status_code=409, detail=f"{label} disappeared.")
    except OSError as exc:
        raise _filesystem_http_exception(
            exc,
            conflict_detail=f"{label} could not be safely inspected.",
            server_detail="AGENTS.md path inspection failed.",
        ) from exc

    if not stat.S_ISREG(path_status.st_mode):
        raise HTTPException(status_code=409, detail=f"{label} is not a regular file.")
    if path_status.st_nlink != 1:
        raise HTTPException(status_code=409, detail=f"{label} has an unsafe hardlink count.")
    return path_status


def _open_project_directory(
    project: Path,
) -> tuple[int | None, os.stat_result | None]:
    if not _USE_DIRECTORY_FD:
        return None, None

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = None
    try:
        directory_fd = os.open(project, flags)
        directory_status = os.fstat(directory_fd)
    except OSError as exc:
        if directory_fd is not None:
            _close_descriptor(directory_fd)
        raise _filesystem_http_exception(
            exc,
            conflict_detail="Selected project directory could not be opened safely.",
            server_detail="AGENTS.md project directory could not be opened.",
        ) from exc

    if not stat.S_ISDIR(directory_status.st_mode):
        os.close(directory_fd)
        raise HTTPException(status_code=409, detail="Selected project descriptor is not a directory.")
    return directory_fd, directory_status


def _validate_directory_identity(
    project: Path,
    directory_fd: int | None,
    directory_status: os.stat_result | None,
) -> None:
    if directory_fd is None or directory_status is None:
        return

    path_status = _inspect_directory(project, "Selected project directory")
    try:
        current_status = os.fstat(directory_fd)
    except OSError as exc:
        raise _filesystem_http_exception(
            exc,
            conflict_detail="Selected project descriptor could not be safely inspected.",
            server_detail="AGENTS.md project directory inspection failed.",
        ) from exc
    if not stat.S_ISDIR(current_status.st_mode):
        raise HTTPException(status_code=409, detail="Selected project descriptor is not a directory.")
    if _identity(current_status) != _identity(directory_status) or _identity(path_status) != _identity(directory_status):
        raise HTTPException(status_code=403, detail="Selected project directory changed during the write.")


def _open_exclusive(
    directory_fd: int | None,
    project: Path,
    filename: str,
) -> int:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if directory_fd is not None:
        return os.open(filename, flags, _FILE_MODE, dir_fd=directory_fd)
    return os.open(project / filename, flags, _FILE_MODE)


def _create_temporary_file(
    directory_fd: int | None,
    project: Path,
    target_name: str,
) -> tuple[str, int]:
    for _ in range(_TEMP_ATTEMPTS):
        temporary_name = f".codexforge-{target_name}-{secrets.token_hex(12)}.tmp"
        try:
            return temporary_name, _open_exclusive(directory_fd, project, temporary_name)
        except FileExistsError:
            continue
    raise HTTPException(status_code=409, detail="A unique temporary AGENTS.md file could not be created.")


def _descriptor_status(file_descriptor: int, label: str) -> os.stat_result:
    try:
        file_status = os.fstat(file_descriptor)
    except OSError as exc:
        raise _filesystem_http_exception(
            exc,
            conflict_detail=f"{label} descriptor could not be safely inspected.",
            server_detail="AGENTS.md file descriptor inspection failed.",
        ) from exc
    return file_status


def _require_safe_file_status(file_status: os.stat_result, label: str) -> None:
    if not stat.S_ISREG(file_status.st_mode):
        raise HTTPException(status_code=409, detail=f"{label} descriptor is not a regular file.")
    if file_status.st_nlink != 1:
        raise HTTPException(status_code=409, detail=f"{label} descriptor has an unsafe hardlink count.")


def _validate_open_file(file_descriptor: int, label: str) -> os.stat_result:
    file_status = _descriptor_status(file_descriptor, label)
    _require_safe_file_status(file_status, label)
    return file_status


def _write_and_sync(file_descriptor: int, content: str) -> None:
    try:
        remaining = memoryview(content.encode("utf-8"))
        while remaining:
            written = os.write(file_descriptor, remaining)
            if written <= 0:
                raise OSError(errno.EIO, "AGENTS.md write made no progress.")
            remaining = remaining[written:]
        os.fsync(file_descriptor)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="AGENTS.md content could not be persisted.") from exc


def _link_file(
    directory_fd: int | None,
    project: Path,
    temporary_name: str,
    target_name: str,
) -> None:
    options: dict[str, object] = {}
    if os.link in os.supports_follow_symlinks:
        options["follow_symlinks"] = False
    if directory_fd is not None and os.link in os.supports_dir_fd:
        os.link(
            temporary_name,
            target_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            **options,
        )
        return
    os.link(project / temporary_name, project / target_name, **options)


def _replace_file(
    directory_fd: int | None,
    project: Path,
    temporary_name: str,
    target_name: str,
) -> None:
    # Directory-relative replacement binds the selected directory where Python
    # supports it. Python has no cross-platform conditional replacement tied to
    # the inspected target inode, so a final pathname race remains, including
    # on Windows where these dir_fd operations are unavailable.
    if directory_fd is not None:
        os.replace(
            temporary_name,
            target_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        return
    os.replace(project / temporary_name, project / target_name)


def _unlink_file(
    directory_fd: int | None,
    project: Path,
    filename: str,
) -> None:
    try:
        if directory_fd is not None:
            os.unlink(filename, dir_fd=directory_fd)
        else:
            os.unlink(project / filename)
    except FileNotFoundError:
        return


def _cleanup_created_file(
    directory_fd: int | None,
    project: Path,
    filename: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    if expected_identity is None:
        _unlink_file(directory_fd, project, filename)
        return
    _unlink_owned_file(
        directory_fd,
        project,
        filename,
        expected_identity,
    )


def _unlink_owned_file(
    directory_fd: int | None,
    project: Path,
    filename: str,
    expected_identity: tuple[int, int],
) -> None:
    try:
        if directory_fd is not None:
            path_status = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        else:
            path_status = (project / filename).stat(follow_symlinks=False)
    except FileNotFoundError:
        return

    if _identity(path_status) != expected_identity:
        return
    if directory_fd is not None:
        os.unlink(filename, dir_fd=directory_fd)
    else:
        os.unlink(project / filename)


def _identity(file_status: os.stat_result) -> tuple[int, int]:
    return file_status.st_dev, file_status.st_ino


def _close_descriptor(file_descriptor: int) -> None:
    try:
        os.close(file_descriptor)
    except OSError:
        pass


def _before_create(project: Path, target: Path) -> None:
    # Patched by deterministic race tests.
    return None


def _before_replace(project: Path, target: Path, temporary_path: Path) -> None:
    # Patched by deterministic race tests.
    return None
