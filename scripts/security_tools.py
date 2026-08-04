#!/usr/bin/env python3
"""Install and verify the pinned repository-local security toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat

# security-suppression:
# finding=B404
# justification=Only validated scanner and Docker argument arrays run without a shell.
# owner=modelguard-maintainers
# expires=2026-10-31
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK_PATH = REPOSITORY_ROOT / "security" / "security-tools.lock.json"
REQUIRED_TOOLS = frozenset({"actionlint", "shellcheck", "checkov", "trivy", "gitleaks"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
ACTION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class SecurityToolError(RuntimeError):
    """A fail-closed toolchain validation or installation error."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SecurityToolError(f"invalid security tool lock: {path.name}") from error


def _exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise SecurityToolError(f"{context} has unexpected or missing fields")


def load_lock(path: Path = DEFAULT_LOCK_PATH) -> dict[str, Any]:
    """Load and strictly validate the single security-tool source of truth."""

    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise SecurityToolError("security tool lock root must be an object")
    _exact_keys(payload, {"schema_version", "platform", "tools", "github_actions"}, "lock")
    if payload["schema_version"] != "modelguard.security-tools.v1":
        raise SecurityToolError("security tool lock schema is unsupported")
    if payload["platform"] != "linux-x86_64":
        raise SecurityToolError("security tool lock platform is unsupported")

    tools = payload["tools"]
    if not isinstance(tools, dict) or set(tools) != REQUIRED_TOOLS:
        raise SecurityToolError(
            "security tool lock must contain exactly the five required scanners"
        )
    for name, raw in tools.items():
        if not isinstance(raw, dict):
            raise SecurityToolError(f"{name} lock entry must be an object")
        version = raw.get("version")
        if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
            raise SecurityToolError(f"{name} version must be an exact semantic version")
        version_args = raw.get("version_args")
        if (
            not isinstance(version_args, list)
            or not version_args
            or not all(isinstance(item, str) and item for item in version_args)
        ):
            raise SecurityToolError(f"{name} version command is invalid")
        if raw.get("kind") == "archive":
            _exact_keys(
                raw,
                {"kind", "version", "url", "sha256", "archive_member", "version_args"},
                name,
            )
            url = raw["url"]
            if (
                not isinstance(url, str)
                or not url.startswith("https://github.com/")
                or f"/v{version}/" not in url
                or any(token in url.lower() for token in ("latest", "/main/", "/master/"))
            ):
                raise SecurityToolError(f"{name} archive URL is not an immutable release URL")
            if (
                not isinstance(raw["sha256"], str)
                or SHA256_PATTERN.fullmatch(raw["sha256"]) is None
            ):
                raise SecurityToolError(f"{name} archive SHA-256 is invalid")
            member = raw["archive_member"]
            if not isinstance(member, str) or not _safe_member(member):
                raise SecurityToolError(f"{name} archive member is unsafe")
        elif raw.get("kind") == "oci":
            _exact_keys(raw, {"kind", "version", "image", "platform", "version_args"}, name)
            image = raw["image"]
            expected = rf"^[a-z0-9./_-]+:{re.escape(version)}@sha256:[0-9a-f]{{64}}$"
            if not isinstance(image, str) or re.fullmatch(expected, image) is None:
                raise SecurityToolError(f"{name} image must use an exact tag and digest")
            if raw["platform"] != "linux/amd64":
                raise SecurityToolError(f"{name} OCI platform is unsupported")
        else:
            raise SecurityToolError(f"{name} tool kind is unsupported")

    actions = payload["github_actions"]
    if not isinstance(actions, dict) or not actions:
        raise SecurityToolError("GitHub Action pin registry must be a non-empty object")
    for name, raw in actions.items():
        if not isinstance(name, str) or "/" not in name or not isinstance(raw, dict):
            raise SecurityToolError("GitHub Action pin entry is invalid")
        _exact_keys(raw, {"version", "commit"}, f"GitHub Action {name}")
        if (
            not isinstance(raw["version"], str)
            or VERSION_PATTERN.fullmatch(raw["version"]) is None
            or not isinstance(raw["commit"], str)
            or ACTION_PATTERN.fullmatch(raw["commit"]) is None
        ):
            raise SecurityToolError(f"GitHub Action {name} is not immutably pinned")
    return payload


def _safe_member(value: str) -> bool:
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and value not in {"", "."}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_member_sha256(archive: Path, member_name: str) -> str:
    digest = hashlib.sha256()
    try:
        with tarfile.open(archive, mode="r:*") as bundle:
            member = bundle.getmember(member_name)
            if not member.isfile() or not _safe_member(member.name):
                raise SecurityToolError("approved security tool archive member is invalid")
            source = bundle.extractfile(member)
            if source is None:
                raise SecurityToolError("approved security tool archive member is unreadable")
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except (KeyError, tarfile.TarError, OSError) as error:
        raise SecurityToolError("approved security tool archive is malformed") from error
    return digest.hexdigest()


def cache_root() -> Path:
    """Return the ignored repository-local security cache, or an explicit test override."""

    override = os.environ.get("SECURITY_TOOLS_CACHE")
    if override and os.environ.get("MODELGUARD_SECURITY_TOOLS_TEST_OVERRIDE") != "1":
        raise SecurityToolError("security tool cache override is permitted only in isolated tests")
    if override:
        root = Path(override).resolve()
    else:
        repository_cache = REPOSITORY_ROOT / ".cache"
        root_path = repository_cache / "security-tools"
        if repository_cache.is_symlink() or root_path.is_symlink():
            raise SecurityToolError("repository-local security tool cache cannot be a symlink")
        root = root_path.resolve()
        if REPOSITORY_ROOT not in root.parents:
            raise SecurityToolError("security tool cache must remain inside the repository")
    git_directory = REPOSITORY_ROOT / ".git"
    if root in (REPOSITORY_ROOT, git_directory) or git_directory in root.parents:
        raise SecurityToolError("security tool cache path is unsafe")
    return root


def _mkdir(path: Path) -> None:
    if path.is_symlink():
        raise SecurityToolError("security tool cache directory cannot be a symlink")
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise SecurityToolError("security tool cache directory is unsafe")
    path.chmod(0o700)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _mkdir(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _download(url: str, destination: Path, expected_sha256: str) -> None:
    _mkdir(destination.parent)
    if destination.is_file() and _sha256(destination) == expected_sha256:
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            request = urllib.request.Request(
                url, headers={"User-Agent": "modelguard-security-bootstrap/1"}
            )
            # security-suppression:
            # finding=B310
            # justification=Only exact HTTPS release URLs pass; SHA-256 is verified before use.
            # owner=modelguard-maintainers
            # expires=2026-10-31
            with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
                if response.status != 200:
                    raise SecurityToolError("security tool download returned a non-200 status")
                shutil.copyfileobj(response, output)
            output.flush()
            os.fsync(output.fileno())
        if _sha256(temporary) != expected_sha256:
            raise SecurityToolError("security tool archive checksum mismatch")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    except (OSError, urllib.error.URLError) as error:
        raise SecurityToolError("security tool download failed") from error
    finally:
        temporary.unlink(missing_ok=True)


def _install_archive(name: str, raw: dict[str, Any], root: Path) -> dict[str, str]:
    archive = root / "downloads" / Path(raw["url"]).name
    _download(raw["url"], archive, raw["sha256"])
    destination = root / "bin" / name
    _mkdir(destination.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with tarfile.open(archive, mode="r:*") as bundle:
            members = {member.name: member for member in bundle.getmembers()}
            member = members.get(raw["archive_member"])
            if member is None or not member.isfile() or not _safe_member(member.name):
                raise SecurityToolError(f"{name} archive does not contain the approved binary")
            source = bundle.extractfile(member)
            if source is None:
                raise SecurityToolError(f"{name} approved archive member is unreadable")
            with os.fdopen(descriptor, "wb") as output:
                shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
        temporary.chmod(0o755)
        os.replace(temporary, destination)
    finally:
        with suppress(OSError):
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return {"archive_sha256": _sha256(archive), "binary_sha256": _sha256(destination)}


def _run(command: list[str], *, timeout_seconds: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        # security-suppression:
        # finding=B603
        # justification=Commands are validated argument arrays and never use a shell.
        # owner=modelguard-maintainers
        # expires=2026-10-31
        return subprocess.run(  # nosec B603
            command, check=False, capture_output=True, text=True, timeout=timeout_seconds
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SecurityToolError(f"tool command unavailable: {command[0]}") from error


def _image_digest(image: str) -> str:
    return image.rsplit("@", maxsplit=1)[1]


def _image_present(image: str) -> bool:
    result = _run(["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"])
    if result.returncode != 0:
        return False
    digest = _image_digest(image)
    try:
        repo_digests = json.loads(result.stdout.strip())
    except json.JSONDecodeError as error:
        raise SecurityToolError("Docker returned malformed image metadata") from error
    return isinstance(repo_digests, list) and any(
        isinstance(value, str) and value.endswith(f"@{digest}") for value in repo_digests
    )


def _install_oci(name: str, raw: dict[str, Any], root: Path) -> dict[str, str]:
    image = raw["image"]
    archive = root / "oci" / f"{name}-{raw['version']}-linux-amd64.tar"
    _mkdir(archive.parent)
    if _image_present(image) and archive.is_file():
        return {"image_digest": _image_digest(image), "archive_sha256": _sha256(archive)}
    if not _image_present(image) and archive.is_file():
        loaded = _run(["docker", "load", "--input", str(archive)], timeout_seconds=600)
        if loaded.returncode != 0:
            raise SecurityToolError(f"cached {name} OCI archive could not be loaded")
    if not _image_present(image):
        pulled = _run(["docker", "pull", "--platform", raw["platform"], image], timeout_seconds=600)
        if pulled.returncode != 0:
            raise SecurityToolError(f"exact {name} OCI image could not be retrieved")
    if not _image_present(image):
        raise SecurityToolError(f"{name} OCI digest verification failed")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{archive.name}.", dir=archive.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        saved = _run(["docker", "save", "--output", str(temporary), image], timeout_seconds=600)
        if saved.returncode != 0:
            raise SecurityToolError(f"{name} OCI image could not be cached locally")
        temporary.chmod(0o600)
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return {"image_digest": _image_digest(image), "archive_sha256": _sha256(archive)}


def _version_output(name: str, raw: dict[str, Any], root: Path) -> str:
    if raw["kind"] == "archive":
        command = [str(root / "bin" / name), *raw["version_args"]]
    else:
        container_tmp = str(PurePosixPath("/") / "tmp")
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--tmpfs",
            f"{container_tmp}:rw,noexec,nosuid,size=64m",
            "--env",
            f"HOME={container_tmp}",
            raw["image"],
            *raw["version_args"],
        ]
    result = _run(command)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise SecurityToolError(f"{name} version command failed")
    if re.search(rf"(?<![0-9]){re.escape(raw['version'])}(?![0-9])", output) is None:
        raise SecurityToolError(f"{name} installed version does not match the lock")
    return output


def bootstrap(lock_path: Path = DEFAULT_LOCK_PATH, only: str | None = None) -> dict[str, str]:
    """Download, verify, install, and version-check every approved scanner."""

    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SecurityToolError("the approved security toolchain supports Linux x86_64 only")
    lock = load_lock(lock_path)
    root = cache_root()
    _mkdir(root)
    selected = {only} if only else REQUIRED_TOOLS
    if not selected <= REQUIRED_TOOLS:
        raise SecurityToolError("unknown security tool requested")
    state: dict[str, Any] = {
        "schema_version": "modelguard.security-tools-state.v1",
        "lock_sha256": _sha256(lock_path),
        "tools": {},
    }
    state_path = root / "install-state.json"
    if state_path.is_symlink():
        raise SecurityToolError("security tool installation state cannot be a symlink")
    if state_path.is_file():
        existing = _read_json(state_path)
        if (
            isinstance(existing, dict)
            and existing.get("schema_version") == state["schema_version"]
            and existing.get("lock_sha256") == state["lock_sha256"]
            and isinstance(existing.get("tools"), dict)
        ):
            state["tools"] = existing["tools"]
    versions: dict[str, str] = {}
    for name in sorted(selected):
        raw = lock["tools"][name]
        installed = (
            _install_archive(name, raw, root)
            if raw["kind"] == "archive"
            else _install_oci(name, raw, root)
        )
        state["tools"][name] = installed
        _version_output(name, raw, root)
        versions[name] = raw["version"]
    _atomic_json(state_path, state)
    return versions


def check(lock_path: Path = DEFAULT_LOCK_PATH, only: str | None = None) -> dict[str, str]:
    """Fail unless installed bytes, OCI digest, and reported versions match the lock."""

    lock = load_lock(lock_path)
    root = cache_root()
    state_path = root / "install-state.json"
    if state_path.is_symlink():
        raise SecurityToolError("security tool installation state cannot be a symlink")
    state = _read_json(state_path)
    if not isinstance(state, dict) or state.get("lock_sha256") != _sha256(lock_path):
        raise SecurityToolError("security tool cache is missing or was built from another lock")
    raw_state = state.get("tools")
    if not isinstance(raw_state, dict):
        raise SecurityToolError("security tool installation state is malformed")
    selected = {only} if only else REQUIRED_TOOLS
    if not selected <= REQUIRED_TOOLS:
        raise SecurityToolError("unknown security tool requested")
    versions: dict[str, str] = {}
    for name in sorted(selected):
        raw = lock["tools"][name]
        installed = raw_state.get(name)
        if not isinstance(installed, dict):
            raise SecurityToolError(f"{name} installation state is missing")
        if raw["kind"] == "archive":
            binary = root / "bin" / name
            archive = root / "downloads" / Path(raw["url"]).name
            if (
                not binary.is_file()
                or binary.is_symlink()
                or not archive.is_file()
                or archive.is_symlink()
                or _sha256(archive) != raw["sha256"]
                or _sha256(binary) != _archive_member_sha256(archive, raw["archive_member"])
                or _sha256(binary) != installed.get("binary_sha256")
                or stat.S_IMODE(binary.stat().st_mode) & 0o111 == 0
            ):
                raise SecurityToolError(f"{name} cached bytes failed integrity verification")
        else:
            archive = root / "oci" / f"{name}-{raw['version']}-linux-amd64.tar"
            if (
                not _image_present(raw["image"])
                or not archive.is_file()
                or archive.is_symlink()
                or _sha256(archive) != installed.get("archive_sha256")
                or installed.get("image_digest") != _image_digest(raw["image"])
            ):
                raise SecurityToolError(f"{name} cached OCI image failed integrity verification")
        _version_output(name, raw, root)
        versions[name] = raw["version"]
    return versions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--tool", choices=sorted(REQUIRED_TOOLS))
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--tool", choices=sorted(REQUIRED_TOOLS))
    path_parser = subparsers.add_parser("path")
    path_parser.add_argument("tool", choices=sorted(REQUIRED_TOOLS - {"checkov"}))
    image_parser = subparsers.add_parser("image")
    image_parser.add_argument("tool", choices=["checkov"])
    version_parser = subparsers.add_parser("version")
    version_parser.add_argument("tool", choices=sorted(REQUIRED_TOOLS))
    subparsers.add_parser("versions")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "bootstrap":
            result = bootstrap(args.lock, args.tool)
            print(json.dumps({"status": "installed", "tools": result}, sort_keys=True))
        elif args.command == "check":
            result = check(args.lock, args.tool)
            print(json.dumps({"status": "verified", "tools": result}, sort_keys=True))
        elif args.command == "path":
            check(args.lock, args.tool)
            print(cache_root() / "bin" / args.tool)
        elif args.command == "image":
            check(args.lock, args.tool)
            print(load_lock(args.lock)["tools"][args.tool]["image"])
        elif args.command == "version":
            check(args.lock, args.tool)
            print(load_lock(args.lock)["tools"][args.tool]["version"])
        else:
            result = check(args.lock)
            print(json.dumps(result, sort_keys=True))
    except SecurityToolError as error:
        print(json.dumps({"status": "refused", "reason": str(error)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
