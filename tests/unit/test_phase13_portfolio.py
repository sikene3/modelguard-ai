from __future__ import annotations

from pathlib import Path

import pytest
from scripts.export_portfolio_architecture import parse_mermaid
from scripts.validate_portfolio import (
    PortfolioValidationError,
    _validate_gif,
    _validate_video,
    sensitive_findings,
    validate_markdown_links,
    validate_portfolio,
)


def test_phase13_portfolio_contract_passes(repository_root: Path) -> None:
    summary = validate_portfolio(repository_root)

    assert summary.status == "passed"
    assert summary.required_paths == 15
    assert summary.claims == 30
    assert summary.reviewed_screenshots == 4
    assert summary.media_files == 2
    assert 254 <= summary.demo_video_duration_seconds <= 256
    assert (summary.demo_video_width, summary.demo_video_height) == (1280, 720)
    assert summary.demo_gif_duration_seconds == 15.0
    assert summary.demo_gif_frames >= 2
    assert summary.local_links >= 70
    assert summary.readme_commands >= 10


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("account 123456789012", "aws_account_id"),
        ("arn:aws:s3:::private-example", "aws_arn"),
        ("owner@example.com", "email_address"),
        ("endpoint 198.51.100.10", "non_loopback_ipv4"),
        ("saved under /home/operator/private", "private_absolute_path"),
    ],
)
def test_sensitive_public_text_patterns_fail_closed(text: str, expected: str) -> None:
    assert expected in sensitive_findings(text)


def test_loopback_is_allowed_in_public_quickstart() -> None:
    assert sensitive_findings("http://127.0.0.1:8000/v1/predict") == ()


def test_markdown_validator_rejects_missing_local_target(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("[missing](does-not-exist.md)\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/CASE_STUDY.md").write_text("# Case study\n", encoding="utf-8")
    (tmp_path / "portfolio").mkdir()

    with pytest.raises(PortfolioValidationError, match="missing local link target"):
        validate_markdown_links(tmp_path)


def test_architecture_parser_rejects_unknown_layout_node(tmp_path: Path) -> None:
    source = tmp_path / "architecture.mmd"
    source.write_text(
        "flowchart TB\n    Unknown[Unknown] --> Client[Demo client]\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="diagram nodes do not match renderer layout"):
        parse_mermaid(source)


def test_media_validators_reject_symlinks(repository_root: Path, tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    gif = tmp_path / "drift.gif"
    video.symlink_to(repository_root / "portfolio/assets/demo/modelguard-demo.mp4")
    gif.symlink_to(repository_root / "portfolio/assets/demo/modelguard-drift.gif")

    with pytest.raises(PortfolioValidationError, match="regular file"):
        _validate_video(video)
    with pytest.raises(PortfolioValidationError, match="regular file"):
        _validate_gif(gif)
