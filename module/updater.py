"""GitHub Releases update checks and the detached update helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional


GITHUB_REPOSITORY = "momoying/MoYomi"
LATEST_RELEASE_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases/latest"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPDATE_STATE_PATH = PROJECT_ROOT / "config" / "update_state.json"
VERSION_METADATA_PATH = PROJECT_ROOT / ".moyomi-version.json"
REQUEST_TIMEOUT_SECONDS = 8
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_ALLOWED_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com"}
_PROTECTED_ROOTS = {
    ".git",
    ".venv",
    "config",
    "models",
    "error_screenshots",
    "__pycache__",
}
_PROTECTED_FILES = {".env"}
_REQUIRED_FILES = {"ui.py", "requirements.txt", "module/updater.py"}
_PATCH_METADATA_PATH = ".moyomi-update.json"


def _installed_version() -> str:
    try:
        metadata = json.loads(VERSION_METADATA_PATH.read_text(encoding="utf-8"))
        version = metadata.get("version") if isinstance(metadata, dict) else None
        if isinstance(version, str) and _VERSION_PATTERN.fullmatch(version):
            return version
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    # Source checkouts without release metadata are development builds.
    return "0.0.0"


APP_VERSION = _installed_version()
APP_VERSION_LABEL = "开发版" if APP_VERSION == "0.0.0" else APP_VERSION


class UpdateError(RuntimeError):
    """Raised when an update cannot be checked, prepared, or installed."""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    name: str
    notes: str
    page_url: str
    ota_url: str
    full_url: str


@dataclass(frozen=True)
class PreparedUpdate:
    archive_path: Path
    temporary_dir: Path
    incremental: bool
    changed_files: int


def parse_version(value: str) -> Optional[tuple[int, int, int]]:
    match = _VERSION_PATTERN.fullmatch(str(value).strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    candidate_version = parse_version(candidate)
    current_version = parse_version(current)
    return bool(
        candidate_version is not None
        and current_version is not None
        and candidate_version > current_version
    )


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/zip;q=0.9,*/*;q=0.8",
            "User-Agent": f"MoYomi/{APP_VERSION}",
        },
    )


def check_for_update(
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    current_version: str = APP_VERSION,
) -> Optional[ReleaseInfo]:
    """Resolve GitHub's public latest-release redirect without using its API."""
    try:
        with opener(_request(LATEST_RELEASE_URL), timeout=REQUEST_TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
    except Exception as exc:
        raise UpdateError(f"无法连接 GitHub：{exc}") from exc

    parsed_url = urllib.parse.urlparse(final_url)
    expected_prefix = f"/{GITHUB_REPOSITORY}/releases/tag/"
    if parsed_url.scheme != "https" or parsed_url.hostname != "github.com":
        raise UpdateError("GitHub 返回了无效的 Release 地址")
    if not parsed_url.path.lower().startswith(expected_prefix.lower()):
        raise UpdateError("仓库尚未发布正式 Release")
    tag_name = urllib.parse.unquote(parsed_url.path[len(expected_prefix) :]).strip("/")
    parsed = parse_version(tag_name)
    if parsed is None or not tag_name.startswith("v"):
        raise UpdateError("最新 Release 标签必须使用 v1.2.3 格式")
    if not is_newer_version(tag_name, current_version):
        return None

    page_url = f"https://github.com/{GITHUB_REPOSITORY}/releases/tag/{tag_name}"
    quoted_tag = urllib.parse.quote(tag_name, safe="")
    current_parsed = parse_version(current_version)
    ota_url = ""
    if current_parsed is not None and current_parsed != (0, 0, 0):
        current_tag = f"v{current_version.lstrip('v')}"
        ota_name = f"MoYomi-OTA-{current_tag}_{tag_name}.zip"
        ota_url = (
            f"https://github.com/{GITHUB_REPOSITORY}/releases/download/"
            f"{quoted_tag}/{urllib.parse.quote(ota_name, safe='')}"
        )
    full_name = f"MoYomi-Full-{tag_name}.zip"
    full_url = (
        f"https://github.com/{GITHUB_REPOSITORY}/releases/download/"
        f"{quoted_tag}/{urllib.parse.quote(full_name, safe='')}"
    )
    return ReleaseInfo(
        version=".".join(str(part) for part in parsed),
        tag_name=tag_name,
        name=tag_name,
        notes="请点击“打开发布页”查看完整更新说明。",
        page_url=page_url,
        ota_url=ota_url,
        full_url=full_url,
    )


def _validate_download_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateError("Release 下载地址不是受信任的 GitHub HTTPS 地址")


def _read_limited(response: Any, limit: int, label: str) -> bytes:
    length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
    if length and int(length) > limit:
        raise UpdateError(f"{label}超过大小限制")
    chunks = bytearray()
    while True:
        chunk = response.read(min(1024 * 1024, limit + 1 - len(chunks)))
        if not chunk:
            break
        chunks.extend(chunk)
        if len(chunks) > limit:
            raise UpdateError(f"{label}超过大小限制")
    return bytes(chunks)


def _read_patch_metadata(archive: zipfile.ZipFile) -> Optional[dict[str, Any]]:
    files = [member for member in archive.infolist() if not member.is_dir()]
    if not files:
        return None
    first_parts = {PurePosixPath(member.filename).parts[0] for member in files}
    if len(first_parts) != 1:
        return None
    wrapper = next(iter(first_parts))
    metadata_name = f"{wrapper}/{_PATCH_METADATA_PATH}"
    if metadata_name not in archive.namelist():
        return None
    try:
        metadata = json.loads(archive.read(metadata_name).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise UpdateError("增量更新清单无效") from exc
    if not isinstance(metadata, dict) or metadata.get("kind") != "incremental":
        raise UpdateError("增量更新清单格式无效")
    deleted = metadata.get("deleted")
    files = metadata.get("files")
    if not isinstance(deleted, list) or not all(isinstance(path, str) for path in deleted):
        raise UpdateError("增量更新删除清单无效")
    if not isinstance(files, dict) or not all(
        isinstance(path, str)
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest)
        for path, digest in files.items()
    ):
        raise UpdateError("增量更新文件清单无效")
    if set(deleted) & set(files):
        raise UpdateError("增量更新清单同时包含新增和删除文件")
    for key in ("from_version", "to_version"):
        if not isinstance(metadata.get(key), str) or parse_version(metadata[key]) is None:
            raise UpdateError("增量更新版本信息无效")
    for path in [*deleted, *files]:
        _validate_update_path(path)
    return metadata


def _validate_update_path(relative: str) -> None:
    if "\\" in relative or ":" in relative:
        raise UpdateError("更新包包含不安全路径")
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise UpdateError("更新包包含不安全路径")
    if path.parts[0] in _PROTECTED_ROOTS or relative in _PROTECTED_FILES:
        raise UpdateError("更新清单包含受保护路径")


def _archive_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    files = [member for member in archive.infolist() if not member.is_dir()]
    if not files:
        raise UpdateError("更新压缩包为空")
    if sum(member.file_size for member in files) > MAX_ARCHIVE_BYTES:
        raise UpdateError("更新压缩包解压后超过 500 MB")

    first_parts = {PurePosixPath(member.filename).parts[0] for member in files}
    if len(first_parts) != 1:
        raise UpdateError("更新压缩包目录结构无效")
    wrapper = next(iter(first_parts))
    managed: dict[str, zipfile.ZipInfo] = {}
    for member in files:
        source_path = PurePosixPath(member.filename)
        parts = source_path.parts
        if not parts or parts[0] != wrapper or len(parts) < 2:
            raise UpdateError("更新压缩包目录结构无效")
        relative = PurePosixPath(*parts[1:])
        relative_name = relative.as_posix()
        if "\\" in member.filename or ":" in member.filename:
            raise UpdateError("更新压缩包包含不安全路径")
        if relative.is_absolute() or ".." in relative.parts:
            raise UpdateError("更新压缩包包含不安全路径")
        if member.external_attr >> 16 & 0o170000 == 0o120000:
            raise UpdateError("更新压缩包不能包含符号链接")
        if relative.parts[0] in _PROTECTED_ROOTS or relative.as_posix() in _PROTECTED_FILES:
            continue
        if relative_name == _PATCH_METADATA_PATH:
            continue
        if relative_name in managed:
            raise UpdateError("更新压缩包包含重复路径")
        managed[relative_name] = member

    metadata = _read_patch_metadata(archive)
    if metadata is None and not _REQUIRED_FILES.issubset(managed):
        raise UpdateError("更新压缩包缺少必要程序文件")
    if metadata is not None:
        if set(metadata["files"]) != set(managed):
            raise UpdateError("增量更新文件与清单不一致")
        for relative, member in managed.items():
            digest = hashlib.sha256(archive.read(member)).hexdigest()
            if digest != metadata["files"][relative]:
                raise UpdateError(f"增量更新文件校验失败：{relative}")
    return managed


def validate_archive(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            managed = _archive_members(archive)
            bad_file = archive.testzip()
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError("下载内容不是有效的 ZIP 压缩包") from exc
    if bad_file is not None:
        raise UpdateError(f"更新压缩包已损坏：{bad_file}")
    return sorted(managed)


def _read_archive_version(path: Path) -> Optional[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            files = [member for member in archive.infolist() if not member.is_dir()]
            first_parts = {PurePosixPath(member.filename).parts[0] for member in files}
            if len(first_parts) != 1:
                return None
            wrapper = next(iter(first_parts))
            metadata = json.loads(
                archive.read(f"{wrapper}/.moyomi-version.json").decode("utf-8")
            )
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(metadata, dict):
        return None
    version = metadata.get("version")
    return version if isinstance(version, str) and parse_version(version) else None


def download_release(
    release: ReleaseInfo,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> PreparedUpdate:
    temporary_dir = Path(tempfile.mkdtemp(prefix="moyomi-update-"))
    archive_path = temporary_dir / f"MoYomi-{release.version}.zip"
    try:
        if release.ota_url:
            try:
                _validate_download_url(release.ota_url)
                with opener(_request(release.ota_url), timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    final_url = response.geturl() if hasattr(response, "geturl") else release.ota_url
                    _validate_download_url(final_url)
                    archive_bytes = _read_limited(response, MAX_ARCHIVE_BYTES, "增量更新包")
                archive_path.write_bytes(archive_bytes)
                changed_files = validate_archive(archive_path)
                with zipfile.ZipFile(archive_path) as archive:
                    metadata = _read_patch_metadata(archive)
                if metadata is None:
                    raise UpdateError("发布的增量更新包缺少清单")
                if (
                    metadata["from_version"] != APP_VERSION
                    or metadata["to_version"] != release.version
                    or _read_archive_version(archive_path) != release.version
                ):
                    raise UpdateError("增量更新包版本不匹配")
                return PreparedUpdate(
                    archive_path=archive_path,
                    temporary_dir=temporary_dir,
                    incremental=True,
                    changed_files=len(changed_files),
                )
            except Exception:
                archive_path.unlink(missing_ok=True)

        _validate_download_url(release.full_url)
        with opener(_request(release.full_url), timeout=REQUEST_TIMEOUT_SECONDS) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else release.full_url
            _validate_download_url(final_url)
            archive_bytes = _read_limited(response, MAX_ARCHIVE_BYTES, "完整更新包")
        archive_path.write_bytes(archive_bytes)
        changed_files = len(validate_archive(archive_path))
        if _read_archive_version(archive_path) != release.version:
            raise UpdateError("完整更新包版本与 Release 标签不匹配")
        return PreparedUpdate(
            archive_path=archive_path,
            temporary_dir=temporary_dir,
            incremental=False,
            changed_files=changed_files,
        )
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def _load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def consume_update_result(path: Path = UPDATE_STATE_PATH) -> Optional[dict[str, str]]:
    state = _load_state(path)
    had_legacy_version = state.pop("installed_version", None) is not None
    result = state.pop("last_result", None)
    if not isinstance(result, dict):
        if had_legacy_version:
            _save_state(path, state)
        return None
    _save_state(path, state)
    return {str(key): str(value) for key, value in result.items()}


def _safe_destination(root: Path, relative: str) -> Path:
    destination = (root / Path(relative)).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as exc:
        raise UpdateError("更新文件试图写入程序目录之外") from exc
    return destination


def _restore_files(root: Path, backup: Path, touched: set[str], existed: set[str]) -> None:
    for relative in touched:
        destination = _safe_destination(root, relative)
        if relative in existed:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / Path(relative), destination)
        elif destination.is_file():
            destination.unlink()


def _install_requirements(python_executable: str, requirements: Path) -> None:
    result = subprocess.run(
        [python_executable, "-m", "pip", "install", "-r", str(requirements)],
        cwd=str(requirements.parent),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "pip 执行失败").strip()
        raise UpdateError(f"依赖更新失败：{message[-1000:]}")


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW


def apply_update(
    archive_path: Path,
    root: Path,
    python_executable: str,
    target_version: str,
    *,
    restart: bool = True,
    requirements_installer: Callable[[str, Path], None] = _install_requirements,
) -> bool:
    """Apply a prepared archive. This function is run by the detached helper."""
    root = root.resolve()
    state_path = root / "config" / "update_state.json"
    state = _load_state(state_path)
    state.pop("installed_version", None)
    old_managed = {
        str(item)
        for item in state.get("managed_files", [])
        if isinstance(item, str)
    }
    backup = archive_path.parent / "backup"
    stage = archive_path.parent / "stage"
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)
    backup.mkdir(parents=True)
    stage.mkdir(parents=True)

    try:
        with zipfile.ZipFile(archive_path) as archive:
            metadata = _read_patch_metadata(archive)
            members = _archive_members(archive)
            if metadata is None:
                if _read_archive_version(archive_path) != target_version:
                    raise UpdateError("完整更新包版本与目标版本不匹配")
            elif metadata["to_version"] != target_version:
                raise UpdateError("增量更新包版本与目标版本不匹配")
            deleted_files = set(metadata["deleted"]) if metadata is not None else set()
            if metadata is None:
                new_managed = set(members)
                touched = new_managed | (old_managed - new_managed)
            else:
                new_managed = (old_managed | set(members)) - deleted_files
                touched = set(members) | deleted_files
            for relative, member in members.items():
                destination = _safe_destination(stage, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)

        existed: set[str] = set()
        for relative in touched:
            destination = _safe_destination(root, relative)
            if destination.is_file():
                existed.add(relative)
                backup_file = backup / Path(relative)
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_file)

        old_requirements = (
            (root / "requirements.txt").read_bytes()
            if (root / "requirements.txt").is_file()
            else b""
        )
        staged_requirements = stage / "requirements.txt"
        new_requirements = (
            staged_requirements.read_bytes()
            if staged_requirements.is_file()
            else old_requirements
        )

        try:
            files_to_delete = deleted_files if metadata is not None else old_managed - new_managed
            for relative in files_to_delete:
                destination = _safe_destination(root, relative)
                if destination.is_file():
                    destination.unlink()
            for relative in members:
                source = stage / Path(relative)
                destination = _safe_destination(root, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            if old_requirements != new_requirements:
                requirements_installer(python_executable, root / "requirements.txt")
        except Exception:
            _restore_files(root, backup, touched, existed)
            raise

        state["managed_files"] = sorted(new_managed)
        state["last_result"] = {
            "status": "success",
            "version": target_version,
            "message": f"已成功更新到 {target_version}",
        }
        _save_state(state_path, state)
        success = True
    except Exception as exc:
        state["last_result"] = {
            "status": "error",
            "version": target_version,
            "message": str(exc),
        }
        _save_state(state_path, state)
        success = False

    if restart:
        subprocess.Popen(
            [python_executable, str(root / "ui.py")],
            cwd=str(root),
            creationflags=_creation_flags(),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return success


def _wait_for_process(process_id: int, timeout: float = 30.0) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(synchronize, False, process_id)
        if not handle:
            return
        try:
            result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        finally:
            kernel32.CloseHandle(handle)
        if result == wait_timeout:
            raise UpdateError("等待旧程序退出超时")
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(process_id, 0)
        except OSError:
            return
        time.sleep(0.2)
    raise UpdateError("等待旧程序退出超时")


def launch_installer(
    prepared: PreparedUpdate,
    release: ReleaseInfo,
    *,
    root: Path = PROJECT_ROOT,
    python_executable: str = sys.executable,
    process_id: int = os.getpid(),
) -> None:
    helper = prepared.temporary_dir / "moyomi_update_helper.py"
    shutil.copy2(Path(__file__), helper)
    subprocess.Popen(
        [
            python_executable,
            str(helper),
            "--apply",
            str(prepared.archive_path),
            str(root),
            python_executable,
            release.version,
            str(process_id),
        ],
        cwd=str(prepared.temporary_dir.parent),
        creationflags=_creation_flags(),
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        nargs=5,
        metavar=("ARCHIVE", "ROOT", "PYTHON", "VERSION", "PARENT_PID"),
    )
    args = parser.parse_args()
    if not args.apply:
        return 0
    archive, root, python_executable, version, parent_pid = args.apply
    try:
        _wait_for_process(int(parent_pid))
        success = apply_update(
            Path(archive),
            Path(root),
            python_executable,
            version,
        )
        shutil.rmtree(Path(archive).parent, ignore_errors=True)
        return 0 if success else 1
    except Exception as exc:
        state_path = Path(root) / "config" / "update_state.json"
        state = _load_state(state_path)
        state.pop("installed_version", None)
        state["last_result"] = {
            "status": "error",
            "version": version,
            "message": str(exc),
        }
        _save_state(state_path, state)
        subprocess.Popen(
            [python_executable, str(Path(root) / "ui.py")],
            cwd=str(root),
            creationflags=_creation_flags(),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
