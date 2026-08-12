#!/usr/bin/env python3
"""Validate Phase 13 portfolio paths, claims boundaries, media, and public-text hygiene."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
# security-suppression:
# finding=B404
# justification=Only one resolved local Git enumeration is executed without a shell.
# owner=modelguard-maintainers
# expires=2026-10-31
import subprocess  # nosec B404
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageChops

from scripts.export_portfolio_architecture import parse_mermaid, render_png, render_svg

REQUIRED_PATHS = (
    "README.md",
    "docs/CASE_STUDY.md",
    "portfolio/linkedin-post.md",
    "portfolio/upwork-portfolio.md",
    "portfolio/fiverr-packages.md",
    "portfolio/demo-script.md",
    "portfolio/screenshot-checklist.md",
    "portfolio/architecture.mmd",
    "portfolio/architecture-export.md",
    "portfolio/assets/demo/modelguard-demo.mp4",
    "portfolio/assets/demo/modelguard-drift.gif",
    "portfolio/assets/modelguard-architecture.svg",
    "portfolio/assets/modelguard-architecture.png",
    "portfolio/skills-to-evidence.md",
    "portfolio/claims-ledger.md",
)
MARKETING_PATHS = (
    "README.md",
    "docs/CASE_STUDY.md",
    "portfolio/linkedin-post.md",
    "portfolio/upwork-portfolio.md",
    "portfolio/fiverr-packages.md",
    "portfolio/demo-script.md",
)
SCREENSHOT_PATHS = (
    "reports/evidence/phase-06/healthy-dashboard.png",
    "reports/evidence/phase-06/degraded-dashboard.png",
    "reports/evidence/phase-11/healthy-dashboard-evidence.png",
    "reports/evidence/phase-11/degraded-dashboard-evidence.png",
)
LINK_PATTERN = re.compile(r"\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(?P<heading>.+?)\s*$", re.MULTILINE)
MAKE_TARGET_PATTERN = re.compile(r"^(?P<target>[A-Za-z0-9][A-Za-z0-9_-]*):(?:\s|$)", re.MULTILINE)
COMMAND_PATTERN = re.compile(
    r"^(?:UV_CACHE_DIR=[^ ]+\s+)?(?P<command>make|uv|curl)\b", re.MULTILINE
)
MAKE_COMMAND_PATTERN = re.compile(r"^make\s+(?P<target>[A-Za-z0-9][A-Za-z0-9_-]*)\b", re.MULTILINE)
FENCED_BASH_PATTERN = re.compile(r"```bash\n(?P<body>.*?)\n```", re.DOTALL)
CLAIM_ID_PATTERN = re.compile(r"^\|\s*(CL-[0-9]{2})\s*\|", re.MULTILINE)

SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_account_id", re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")),
    ("aws_arn", re.compile(r"\barn:(?:aws|aws-us-gov|aws-cn):", re.IGNORECASE)),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "email_address",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    ),
    (
        "non_loopback_ipv4",
        re.compile(
            r"(?<![0-9])(?!(?:127\.0\.0\.1)(?![0-9]))"
            r"(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})(?:\."
            r"(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})){3}(?![0-9])"
        ),
    ),
    ("private_absolute_path", re.compile(r"(?:^|[\s`'\"])/(?:home|mnt)/", re.MULTILINE)),
    ("aws_service_endpoint", re.compile(r"https?://[^\s)`]*\.amazonaws\.com\b", re.IGNORECASE)),
)


class PortfolioValidationError(RuntimeError):
    """Raised when a public portfolio contract is incomplete or unsafe."""


@dataclass(frozen=True)
class ValidationSummary:
    schema_version: str
    required_paths: int
    markdown_files: int
    local_links: int
    bash_blocks: int
    readme_commands: int
    make_targets: int
    claims: int
    reviewed_screenshots: int
    media_files: int
    demo_video_duration_seconds: float
    demo_video_width: int
    demo_video_height: int
    demo_gif_duration_seconds: float
    demo_gif_frames: int
    architecture_mmd_sha256: str
    architecture_svg_sha256: str
    architecture_png_sha256: str
    status: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _markdown_slug(heading: str) -> str:
    without_markup = re.sub(r"[`*_~]", "", heading.strip().casefold())
    without_punctuation = re.sub(r"[^\w\s-]", "", without_markup)
    return re.sub(r"[\s-]+", "-", without_punctuation).strip("-")


def sensitive_findings(text: str) -> tuple[str, ...]:
    """Return bounded sensitive-data pattern names found in public text."""

    return tuple(name for name, pattern in SENSITIVE_PATTERNS if pattern.search(text))


def _public_text_paths(repository_root: Path) -> tuple[Path, ...]:
    portfolio_paths = tuple(
        path
        for path in sorted((repository_root / "portfolio").rglob("*"))
        if path.is_file() and path.suffix.casefold() in {".md", ".mmd", ".svg"}
    )
    return (
        repository_root / "README.md",
        repository_root / "docs/CASE_STUDY.md",
        *portfolio_paths,
    )


def _validate_required_paths(repository_root: Path) -> None:
    missing = [
        relative for relative in REQUIRED_PATHS if not (repository_root / relative).is_file()
    ]
    if missing:
        raise PortfolioValidationError(f"missing required portfolio paths: {missing}")


def _validate_file_manifest(repository_root: Path) -> None:
    manifest_path = repository_root / "FILE_MANIFEST.txt"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise PortfolioValidationError("FILE_MANIFEST.txt must be a regular file")
    manifest_paths = manifest_path.read_text(encoding="utf-8").splitlines()
    if not manifest_paths or manifest_paths != sorted(set(manifest_paths)):
        raise PortfolioValidationError("FILE_MANIFEST.txt must be non-empty, sorted, and unique")

    git_binary = shutil.which("git")
    if git_binary is None:
        raise PortfolioValidationError("git is required to validate FILE_MANIFEST.txt parity")
    # security-suppression:
    # finding=B603
    # justification=The resolved executable and every argument are fixed with no shell input.
    # owner=modelguard-maintainers
    # expires=2026-10-31
    completed = subprocess.run(  # nosec B603
        [git_binary, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PortfolioValidationError("git could not enumerate the repository candidate set")
    try:
        candidates = sorted(
            path
            for path in completed.stdout.decode("utf-8").split("\0")
            if path and path != "FILE_MANIFEST.txt"
        )
    except UnicodeDecodeError as error:
        raise PortfolioValidationError("repository candidate paths must be UTF-8") from error

    if manifest_paths != candidates:
        manifest_set = set(manifest_paths)
        candidate_set = set(candidates)
        missing = sorted(manifest_set - candidate_set)[:10]
        unlisted = sorted(candidate_set - manifest_set)[:10]
        raise PortfolioValidationError(
            f"FILE_MANIFEST.txt parity failed: missing={missing}, unlisted={unlisted}"
        )


def _validate_public_hygiene(repository_root: Path) -> None:
    findings: dict[str, tuple[str, ...]] = {}
    for path in _public_text_paths(repository_root):
        matches = sensitive_findings(path.read_text(encoding="utf-8"))
        if matches:
            findings[path.relative_to(repository_root).as_posix()] = matches
    if findings:
        raise PortfolioValidationError(f"sensitive public-text patterns: {findings}")

    for relative in MARKETING_PATHS:
        text = (repository_root / relative).read_text(encoding="utf-8").casefold()
        if "synthetic" not in text:
            raise PortfolioValidationError(f"synthetic-data boundary missing from {relative}")
    if "temporary" not in (repository_root / "README.md").read_text(encoding="utf-8").casefold():
        raise PortfolioValidationError("temporary-cloud boundary missing from README.md")


def _validate_fragment(
    path: Path,
    fragment: str,
    *,
    source: Path,
    repository_root: Path,
) -> None:
    if not fragment or path.suffix.casefold() not in {".md", ".markdown"}:
        return
    headings = {
        _markdown_slug(match.group("heading"))
        for match in HEADING_PATTERN.finditer(path.read_text(encoding="utf-8"))
    }
    if fragment.casefold() not in headings:
        relative_path = path.relative_to(repository_root).as_posix()
        relative_source = source.relative_to(repository_root).as_posix()
        raise PortfolioValidationError(
            f"missing markdown fragment #{fragment} in {relative_path}; "
            f"linked from {relative_source}"
        )


def validate_markdown_links(repository_root: Path) -> tuple[int, int]:
    """Validate every local Markdown link in the public portfolio surface."""

    markdown_paths = tuple(
        path for path in _public_text_paths(repository_root) if path.suffix.casefold() == ".md"
    )
    local_link_count = 0
    for source in markdown_paths:
        text = source.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(text):
            target = match.group("target")
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            local_link_count += 1
            raw_path, _, fragment = target.partition("#")
            resolved = source if not raw_path else (source.parent / raw_path).resolve()
            try:
                resolved.relative_to(repository_root.resolve())
            except ValueError as error:
                relative_source = source.relative_to(repository_root).as_posix()
                raise PortfolioValidationError(
                    f"local link escapes repository: {target} in {relative_source}"
                ) from error
            if not resolved.exists():
                relative_source = source.relative_to(repository_root).as_posix()
                raise PortfolioValidationError(
                    f"missing local link target {target} in {relative_source}"
                )
            _validate_fragment(
                resolved,
                fragment,
                source=source,
                repository_root=repository_root,
            )
    return len(markdown_paths), local_link_count


def _validate_readme_commands(repository_root: Path) -> tuple[int, int, int]:
    readme = (repository_root / "README.md").read_text(encoding="utf-8")
    blocks = tuple(match.group("body") for match in FENCED_BASH_PATTERN.finditer(readme))
    if not blocks:
        raise PortfolioValidationError("README has no bash command blocks")

    make_targets = set(
        MAKE_TARGET_PATTERN.findall((repository_root / "Makefile").read_text(encoding="utf-8"))
    )
    commands: list[str] = []
    used_make_targets: set[str] = set()
    for block in blocks:
        commands.extend(COMMAND_PATTERN.findall(block))
        for match in MAKE_COMMAND_PATTERN.finditer(block):
            target = match.group("target")
            used_make_targets.add(target)
            if target not in make_targets:
                raise PortfolioValidationError(f"README references missing Make target: {target}")

    for command in sorted(set(commands)):
        if shutil.which(command) is None:
            raise PortfolioValidationError(
                f"README command is unavailable on validation host: {command}"
            )

    required_targets = {"setup", "train", "verify-model", "dashboard", "api"}
    missing_targets = required_targets - used_make_targets
    if missing_targets:
        raise PortfolioValidationError(
            f"README quickstart is missing required Make targets: {sorted(missing_targets)}"
        )
    return len(blocks), len(commands), len(used_make_targets)


def _validate_claims(repository_root: Path) -> int:
    text = (repository_root / "portfolio/claims-ledger.md").read_text(encoding="utf-8")
    claim_ids = CLAIM_ID_PATTERN.findall(text)
    if len(claim_ids) != len(set(claim_ids)):
        raise PortfolioValidationError("claims ledger contains duplicate claim IDs")
    if claim_ids != [f"CL-{index:02d}" for index in range(1, 31)]:
        raise PortfolioValidationError("claims ledger must contain contiguous CL-01 through CL-30")
    recording_line = next(
        (line for line in text.splitlines() if line.startswith("| CL-29 |")),
        "",
    )
    if not recording_line.rstrip().endswith("| supported with boundary |"):
        raise PortfolioValidationError("recording/GIF claim CL-29 must be evidence-backed")
    for required_path in (
        "assets/demo/modelguard-demo.mp4",
        "assets/demo/modelguard-drift.gif",
    ):
        if required_path not in recording_line:
            raise PortfolioValidationError(
                f"recording/GIF claim CL-29 is missing media evidence: {required_path}"
            )
    return len(claim_ids)


def _validate_screenshots(repository_root: Path) -> int:
    missing = [path for path in SCREENSHOT_PATHS if not (repository_root / path).is_file()]
    if missing:
        raise PortfolioValidationError(f"reviewed screenshot evidence is missing: {missing}")
    return len(SCREENSHOT_PATHS)


def _mp4_boxes(data: bytes, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    position = start
    while position < end:
        if position + 8 > end:
            raise PortfolioValidationError("MP4 contains a truncated box header")
        size = struct.unpack_from(">I", data, position)[0]
        box_type = data[position + 4 : position + 8]
        header_size = 8
        if size == 1:
            if position + 16 > end:
                raise PortfolioValidationError("MP4 contains a truncated extended box header")
            size = struct.unpack_from(">Q", data, position + 8)[0]
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            raise PortfolioValidationError("MP4 contains an invalid box size")
        yield box_type, position + header_size, position + size
        position += size


def _single_mp4_box(data: bytes, start: int, end: int, expected_type: bytes) -> tuple[int, int]:
    matches = [
        (payload_start, box_end)
        for box_type, payload_start, box_end in _mp4_boxes(data, start, end)
        if box_type == expected_type
    ]
    if len(matches) != 1:
        label = expected_type.decode("ascii", errors="replace")
        raise PortfolioValidationError(f"MP4 must contain exactly one {label} box")
    return matches[0]


def _mp4_duration(data: bytes, mvhd_start: int, mvhd_end: int) -> float:
    if mvhd_end - mvhd_start < 20:
        raise PortfolioValidationError("MP4 movie header is truncated")
    version = data[mvhd_start]
    if version == 0:
        timescale = int(struct.unpack_from(">I", data, mvhd_start + 12)[0])
        duration = int(struct.unpack_from(">I", data, mvhd_start + 16)[0])
    elif version == 1:
        if mvhd_end - mvhd_start < 32:
            raise PortfolioValidationError("MP4 version-1 movie header is truncated")
        timescale = int(struct.unpack_from(">I", data, mvhd_start + 20)[0])
        duration = int(struct.unpack_from(">Q", data, mvhd_start + 24)[0])
    else:
        raise PortfolioValidationError("MP4 movie header version is unsupported")
    if timescale <= 0 or duration <= 0:
        raise PortfolioValidationError("MP4 movie timing is invalid")
    return float(duration) / float(timescale)


def _mp4_video_dimensions(data: bytes, moov_start: int, moov_end: int) -> tuple[int, int]:
    video_tracks: list[tuple[int, int]] = []
    for box_type, trak_start, trak_end in _mp4_boxes(data, moov_start, moov_end):
        if box_type != b"trak":
            continue
        mdia_start, mdia_end = _single_mp4_box(data, trak_start, trak_end, b"mdia")
        hdlr_start, hdlr_end = _single_mp4_box(data, mdia_start, mdia_end, b"hdlr")
        if hdlr_end - hdlr_start < 12:
            raise PortfolioValidationError("MP4 handler box is truncated")
        if data[hdlr_start + 8 : hdlr_start + 12] == b"vide":
            video_tracks.append((trak_start, trak_end))
    if len(video_tracks) != 1:
        raise PortfolioValidationError("MP4 must contain exactly one video track")

    trak_start, trak_end = video_tracks[0]
    tkhd_start, tkhd_end = _single_mp4_box(data, trak_start, trak_end, b"tkhd")
    if tkhd_end - tkhd_start < 8:
        raise PortfolioValidationError("MP4 track header is truncated")
    width_fixed, height_fixed = struct.unpack_from(">II", data, tkhd_end - 8)
    width = width_fixed >> 16
    height = height_fixed >> 16
    if b"avc1" not in data[trak_start:trak_end]:
        raise PortfolioValidationError("MP4 video track is not H.264/AVC")
    return width, height


def _validate_video(path: Path) -> tuple[float, int, int]:
    if path.is_symlink() or not path.is_file():
        raise PortfolioValidationError("demo MP4 must be a regular file")
    size = path.stat().st_size
    if not 1_000_000 <= size < 100 * 1024 * 1024:
        raise PortfolioValidationError("demo MP4 size is outside the reviewed GitHub boundary")
    data = path.read_bytes()
    _single_mp4_box(data, 0, len(data), b"ftyp")
    moov_start, moov_end = _single_mp4_box(data, 0, len(data), b"moov")
    mvhd_start, mvhd_end = _single_mp4_box(data, moov_start, moov_end, b"mvhd")
    duration = _mp4_duration(data, mvhd_start, mvhd_end)
    width, height = _mp4_video_dimensions(data, moov_start, moov_end)
    if not 180 <= duration <= 300:
        raise PortfolioValidationError("demo MP4 duration must be between 180 and 300 seconds")
    if (width, height) != (1280, 720):
        raise PortfolioValidationError("demo MP4 resolution must be exactly 1280x720")
    return duration, width, height


def _validate_gif(path: Path) -> tuple[float, int]:
    if path.is_symlink() or not path.is_file():
        raise PortfolioValidationError("demo GIF must be a regular file")
    if path.stat().st_size >= 10 * 1024 * 1024:
        raise PortfolioValidationError("demo GIF exceeds the reviewed GitHub size boundary")
    with Image.open(path) as image:
        is_animated = getattr(image, "is_animated", False)
        frame_count = getattr(image, "n_frames", 1)
        if (
            image.format != "GIF"
            or is_animated is not True
            or not isinstance(frame_count, int)
            or frame_count < 2
        ):
            raise PortfolioValidationError("demo GIF must be an animated GIF")
        if image.size != (960, 540):
            raise PortfolioValidationError("demo GIF resolution must be exactly 960x540")
        durations: list[int] = []
        image.seek(0)
        first = image.convert("RGB")
        for index in range(frame_count):
            image.seek(index)
            duration = image.info.get("duration")
            if not isinstance(duration, int) or duration <= 0:
                raise PortfolioValidationError("demo GIF frame duration is invalid")
            durations.append(duration)
        image.seek(frame_count - 1)
        last = image.convert("RGB")
    duration_seconds = sum(durations) / 1000
    if not 8 <= duration_seconds <= 15:
        raise PortfolioValidationError("demo GIF duration must be between 8 and 15 seconds")
    if ImageChops.difference(first, last).getbbox() is None:
        raise PortfolioValidationError("demo GIF does not contain a visible state transition")
    return duration_seconds, frame_count


def _validate_media(repository_root: Path) -> tuple[float, int, int, float, int]:
    video_duration, video_width, video_height = _validate_video(
        repository_root / "portfolio/assets/demo/modelguard-demo.mp4"
    )
    gif_duration, gif_frames = _validate_gif(
        repository_root / "portfolio/assets/demo/modelguard-drift.gif"
    )
    return video_duration, video_width, video_height, gif_duration, gif_frames


def _validate_architecture(repository_root: Path) -> tuple[str, str, str]:
    source = repository_root / "portfolio/architecture.mmd"
    svg = repository_root / "portfolio/assets/modelguard-architecture.svg"
    png = repository_root / "portfolio/assets/modelguard-architecture.png"
    diagram = parse_mermaid(source)
    with tempfile.TemporaryDirectory(prefix="modelguard-portfolio-") as temporary:
        temporary_root = Path(temporary)
        generated_svg = temporary_root / "architecture.svg"
        generated_png = temporary_root / "architecture.png"
        render_svg(diagram, generated_svg)
        render_png(diagram, generated_png)
        if generated_svg.read_bytes() != svg.read_bytes():
            raise PortfolioValidationError("architecture SVG is stale relative to Mermaid source")
        if generated_png.read_bytes() != png.read_bytes():
            raise PortfolioValidationError("architecture PNG is stale relative to Mermaid source")
    return _sha256(source), _sha256(svg), _sha256(png)


def validate_portfolio(repository_root: Path) -> ValidationSummary:
    """Run the complete non-network Phase 13 public-asset validation."""

    root = repository_root.resolve()
    _validate_file_manifest(root)
    _validate_required_paths(root)
    markdown_files, local_links = validate_markdown_links(root)
    _validate_public_hygiene(root)
    bash_blocks, readme_commands, make_targets = _validate_readme_commands(root)
    claims = _validate_claims(root)
    screenshots = _validate_screenshots(root)
    video_duration, video_width, video_height, gif_duration, gif_frames = _validate_media(root)
    mmd_sha, svg_sha, png_sha = _validate_architecture(root)
    return ValidationSummary(
        schema_version="modelguard.portfolio-validation.v2",
        required_paths=len(REQUIRED_PATHS),
        markdown_files=markdown_files,
        local_links=local_links,
        bash_blocks=bash_blocks,
        readme_commands=readme_commands,
        make_targets=make_targets,
        claims=claims,
        reviewed_screenshots=screenshots,
        media_files=2,
        demo_video_duration_seconds=round(video_duration, 6),
        demo_video_width=video_width,
        demo_video_height=video_height,
        demo_gif_duration_seconds=round(gif_duration, 6),
        demo_gif_frames=gif_frames,
        architecture_mmd_sha256=mmd_sha,
        architecture_svg_sha256=svg_sha,
        architecture_png_sha256=png_sha,
        status="passed",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    return parser


def main() -> int:
    """Validate the repository portfolio surface and emit one bounded JSON summary."""

    args = _parser().parse_args()
    try:
        result = validate_portfolio(args.repository_root)
    except (OSError, ValueError, PortfolioValidationError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "modelguard.portfolio-validation.v2",
                    "status": "failed",
                    "reason": str(error),
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
