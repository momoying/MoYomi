"""Build full and incremental update packages from a version tag."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath


PROTECTED_ROOTS = {".git", ".venv", "config", "models", "error_screenshots", "__pycache__"}
PROTECTED_FILES = {".env"}
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def git(*args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return result.stdout.decode("utf-8") if text else result.stdout


def version(tag: str) -> tuple[int, int, int] | None:
    if not tag.startswith("v"):
        return None
    match = VERSION.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def previous_tag(target_tag: str) -> str | None:
    target_version = version(target_tag)
    if target_version is None:
        raise ValueError(f"Invalid release tag: {target_tag}")
    candidates = [
        tag for tag in str(git("tag", "--list")).splitlines()
        if tag != target_tag and version(tag) is not None and version(tag) < target_version
    ]
    candidates.sort(key=version, reverse=True)
    for candidate in candidates:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", candidate, target_tag],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return candidate
    return None


def safe_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(
        value
        and "\\" not in value
        and ":" not in value
        and not path.is_absolute()
        and ".." not in path.parts
        and path.parts
        and path.parts[0] not in PROTECTED_ROOTS
        and value not in PROTECTED_FILES
        and value != ".moyomi-update.json"
        and value != ".moyomi-version.json"
    )


def version_metadata(tag: str, parsed_version: tuple[int, int, int]) -> bytes:
    return json.dumps(
        {"version": ".".join(map(str, parsed_version)), "tag": tag},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def build(base_tag: str, target_tag: str, output: Path) -> int:
    base_version, target_version = version(base_tag), version(target_tag)
    if base_version is None or target_version is None or base_version >= target_version:
        raise ValueError("Tags must be increasing semantic versions")

    raw = git("diff", "--name-status", "-z", "--no-renames", base_tag, target_tag, text=False)
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    changes: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        status = fields[index].decode("ascii")
        path = fields[index + 1].decode("utf-8")
        if not safe_path(path):
            continue
        if status != "D":
            changes.append((status, path))
    deleted = [
        fields[index + 1].decode("utf-8")
        for index in range(0, len(fields), 2)
        if fields[index].decode("ascii") == "D"
        and safe_path(fields[index + 1].decode("utf-8"))
    ]
    wrapper = f"momoying-MoYomi-{target_tag}"
    files: dict[str, str] = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for _status, path in changes:
            content = git("show", f"{target_tag}:{path}", text=False)
            assert isinstance(content, bytes)
            archive.writestr(f"{wrapper}/{path}", content)
            files[path] = hashlib.sha256(content).hexdigest()
        version_file = version_metadata(target_tag, target_version)
        archive.writestr(f"{wrapper}/.moyomi-version.json", version_file)
        files[".moyomi-version.json"] = hashlib.sha256(version_file).hexdigest()
        manifest = {
            "kind": "incremental",
            "from_version": ".".join(map(str, base_version)),
            "to_version": ".".join(map(str, target_version)),
            "deleted": sorted(deleted),
            "files": files,
        }
        archive.writestr(
            f"{wrapper}/.moyomi-update.json",
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        )
    print(f"Built {output} ({len(files)} changed, {len(deleted)} deleted)")
    return 0


def build_full(target_tag: str, output: Path) -> int:
    target_version = version(target_tag)
    if target_version is None:
        raise ValueError(f"Invalid release tag: {target_tag}")
    paths = str(git("ls-tree", "-r", "--name-only", target_tag)).splitlines()
    wrapper = f"momoying-MoYomi-{target_tag}"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if not safe_path(path):
                continue
            content = git("show", f"{target_tag}:{path}", text=False)
            assert isinstance(content, bytes)
            archive.writestr(f"{wrapper}/{path}", content)
        archive.writestr(
            f"{wrapper}/.moyomi-version.json",
            version_metadata(target_tag, target_version),
        )
    print(f"Built full package {output} ({len(paths)} tracked paths checked)")
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: build_update_package.py <vX.Y.Z-tag> <output-dir>", file=sys.stderr)
        return 2
    target_tag, output_dir = sys.argv[1], Path(sys.argv[2])
    target_version = version(target_tag)
    if target_version is None:
        raise ValueError(f"Invalid release tag: {target_tag}")
    result = build_full(target_tag, output_dir / f"MoYomi-Full-{target_tag}.zip")
    base_tag = previous_tag(target_tag)
    if base_tag is None:
        print(f"No previous semantic-version ancestor found for {target_tag}; skipping OTA.")
        return result
    output = output_dir / f"MoYomi-OTA-{base_tag}_{target_tag}.zip"
    return build(base_tag, target_tag, output) or result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError) as exc:
        print(f"Failed to build OTA package: {exc}", file=sys.stderr)
        raise SystemExit(1)
