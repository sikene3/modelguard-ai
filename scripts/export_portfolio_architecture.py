#!/usr/bin/env python3
"""Render the fixed portfolio Mermaid graph to shareable SVG and PNG assets."""

from __future__ import annotations

import argparse
import html
import math
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS_WIDTH = 2000
CANVAS_HEIGHT = 1350
EDGE_PATTERN = re.compile(
    r"^\s*(?P<source>[A-Za-z][A-Za-z0-9]*)(?:\[(?P<source_label>[^]]+)\])?\s*"
    r"-->\s*(?P<target>[A-Za-z][A-Za-z0-9]*)(?:\[(?P<target_label>[^]]+)\])?\s*$"
)


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)


@dataclass(frozen=True)
class Diagram:
    labels: dict[str, str]
    edges: tuple[tuple[str, str], ...]


BOXES: dict[str, Box] = {
    "Client": Box(50, 280, 220, 100),
    "Edge": Box(340, 280, 250, 100),
    "API": Box(690, 280, 290, 105),
    "Events": Box(1090, 280, 360, 105),
    "Model": Box(690, 145, 420, 105),
    "Scheduler": Box(50, 610, 300, 105),
    "Monitor": Box(440, 610, 310, 110),
    "Reports": Box(850, 610, 350, 110),
    "Dashboard": Box(1300, 610, 320, 110),
    "Alerts": Box(1660, 810, 290, 105),
    "Observability": Box(850, 830, 360, 110),
    "Delivery": Box(390, 1060, 520, 150),
}

ROUTES: dict[tuple[str, str], tuple[tuple[float, float], ...]] = {
    ("Edge", "Dashboard"): ((630, 465), (1260, 465), (1260, 665)),
    ("Model", "Monitor"): ((650, 235), (390, 515), (390, 665)),
    ("Events", "Monitor"): ((1050, 470), (790, 470), (790, 555), (595, 555)),
    ("Monitor", "Alerts"): ((790, 770), (1620, 770), (1620, 862)),
    ("API", "Observability"): ((820, 500), (820, 780), (900, 780)),
    ("Dashboard", "Observability"): ((1260, 780),),
    ("Delivery", "API"): ((335, 1020), (335, 520), (650, 520), (650, 332)),
    ("Delivery", "Monitor"): ((595, 1020), (595, 760)),
    ("Delivery", "Dashboard"): ((970, 1020), (1660, 1020), (1660, 665)),
}

COMPUTE_NODES = frozenset({"API", "Dashboard", "Monitor"})
DATA_NODES = frozenset({"Model", "Events", "Reports"})
CONTROL_NODES = frozenset(
    {
        "Edge",
        "Scheduler",
        "Alerts",
        "Observability",
        "Delivery",
    }
)


def parse_mermaid(path: Path) -> Diagram:
    """Parse the restricted node/edge subset used by the committed portfolio graph."""

    labels: dict[str, str] = {}
    edges: list[tuple[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("flowchart ")
            or stripped.startswith("classDef ")
            or stripped.startswith("class ")
        ):
            continue
        match = EDGE_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(f"unsupported Mermaid syntax on line {line_number}")
        source = match.group("source")
        target = match.group("target")
        for node, label in (
            (source, match.group("source_label")),
            (target, match.group("target_label")),
        ):
            if label is not None:
                existing = labels.setdefault(node, label)
                if existing != label:
                    raise ValueError(f"conflicting label for node {node}")
        edges.append((source, target))

    expected = set(BOXES)
    if set(labels) != expected:
        missing = sorted(expected - set(labels))
        extra = sorted(set(labels) - expected)
        raise ValueError(
            f"diagram nodes do not match renderer layout; missing={missing}, extra={extra}"
        )
    if any(source not in expected or target not in expected for source, target in edges):
        raise ValueError("diagram edge references an unknown node")
    if len(edges) != len(set(edges)):
        raise ValueError("diagram contains a duplicate edge")
    return Diagram(labels=labels, edges=tuple(edges))


def _palette(node: str) -> tuple[str, str]:
    if node in COMPUTE_NODES:
        return ("#e8f2ff", "#2563eb")
    if node in DATA_NODES:
        return ("#ecfdf5", "#059669")
    if node in CONTROL_NODES:
        return ("#fff7ed", "#ea580c")
    return ("#f8fafc", "#64748b")


def _boundary_toward(box: Box, target: tuple[float, float]) -> tuple[float, float]:
    center = box.center
    delta_x = target[0] - center[0]
    delta_y = target[1] - center[1]
    scale_x = math.inf if delta_x == 0 else (box.width / 2) / abs(delta_x)
    scale_y = math.inf if delta_y == 0 else (box.height / 2) / abs(delta_y)
    scale = min(scale_x, scale_y)
    return (center[0] + delta_x * scale, center[1] + delta_y * scale)


def _edge_path(source: str, target: str) -> tuple[tuple[float, float], ...]:
    intermediate = ROUTES.get((source, target), ())
    first_target = intermediate[0] if intermediate else BOXES[target].center
    last_source = intermediate[-1] if intermediate else BOXES[source].center
    return (
        _boundary_toward(BOXES[source], first_target),
        *intermediate,
        _boundary_toward(BOXES[target], last_source),
    )


def _arrow_polygon(
    start: tuple[float, float], end: tuple[float, float], size: float = 13
) -> list[tuple[float, float]]:
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    return [
        end,
        (
            end[0] - size * math.cos(angle - math.pi / 6),
            end[1] - size * math.sin(angle - math.pi / 6),
        ),
        (
            end[0] - size * math.cos(angle + math.pi / 6),
            end[1] - size * math.sin(angle + math.pi / 6),
        ),
    ]


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    paths = (
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/share/fonts/dejavu") / name,
    )
    for path in paths:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _wrapped_lines(label: str, width: int = 18) -> list[str]:
    return textwrap.wrap(label, width=width, break_long_words=False) or [label]


def render_png(diagram: Diagram, output: Path) -> None:
    """Render the parsed graph to a high-resolution PNG."""

    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#ffffff")
    draw = ImageDraw.Draw(image)
    title_font = _font(42, bold=True)
    subtitle_font = _font(23)
    node_font = _font(23, bold=True)
    legend_font = _font(20)
    edge_color = "#64748b"

    draw.text(
        (60, 34), "ModelGuard AI · temporary AWS demo architecture", fill="#172033", font=title_font
    )
    draw.text(
        (60, 92),
        "Synthetic data · restricted access · immutable identities · scheduled evidence windows",
        fill="#475569",
        font=subtitle_font,
    )

    for source, target in diagram.edges:
        path = _edge_path(source, target)
        draw.line(path, fill=edge_color, width=4, joint="curve")
        draw.polygon(_arrow_polygon(path[-2], path[-1]), fill=edge_color)

    for node, box in BOXES.items():
        fill, stroke = _palette(node)
        draw.rounded_rectangle(
            (box.x, box.y, box.x + box.width, box.y + box.height),
            radius=18,
            fill=fill,
            outline=stroke,
            width=4,
        )
        lines = _wrapped_lines(diagram.labels[node])
        spacing = 8
        line_heights = [draw.textbbox((0, 0), line, font=node_font)[3] for line in lines]
        total_height = sum(line_heights) + spacing * (len(lines) - 1)
        cursor_y = box.y + (box.height - total_height) / 2
        for line, line_height in zip(lines, line_heights, strict=True):
            bounds = draw.textbbox((0, 0), line, font=node_font)
            line_width = bounds[2] - bounds[0]
            draw.text(
                (box.x + (box.width - line_width) / 2, cursor_y),
                line,
                fill="#172033",
                font=node_font,
            )
            cursor_y += line_height + spacing

    legend_y = 1290
    legends = (
        ("Compute", "#e8f2ff", "#2563eb"),
        ("Data/evidence", "#ecfdf5", "#059669"),
        ("Control/managed service", "#fff7ed", "#ea580c"),
        ("Client", "#f8fafc", "#64748b"),
    )
    cursor_x = 60
    for label, fill, stroke in legends:
        draw.rounded_rectangle(
            (cursor_x, legend_y, cursor_x + 34, legend_y + 24),
            radius=5,
            fill=fill,
            outline=stroke,
            width=2,
        )
        draw.text((cursor_x + 46, legend_y - 1), label, fill="#475569", font=legend_font)
        cursor_x += 280 if label != "Control/managed service" else 380

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def render_svg(diagram: Diagram, output: Path) -> None:
    """Render the parsed graph to an accessible standalone SVG."""

    parts = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1350" '
            'viewBox="0 0 2000 1350" role="img" aria-labelledby="title desc">'
        ),
        '<title id="title">ModelGuard AI temporary AWS demo architecture</title>',
        (
            '<desc id="desc">A synthetic demo client reaches restricted ECS API and dashboard '
            "services. Prediction events flow through Firehose to S3, a scheduled monitor writes "
            "reports and alerts, and GitHub OIDC plus ECR and Terraform control delivery.</desc>"
        ),
        '<rect width="2000" height="1350" fill="#ffffff"/>',
        (
            '<text x="60" y="70" font-family="DejaVu Sans,Arial,sans-serif" font-size="42" '
            'font-weight="700" fill="#172033">ModelGuard AI · temporary AWS demo '
            "architecture</text>"
        ),
        (
            '<text x="60" y="112" font-family="DejaVu Sans,Arial,sans-serif" font-size="23" '
            'fill="#475569">Synthetic data · restricted access · immutable identities · '
            "scheduled evidence windows</text>"
        ),
        (
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/></marker></defs>'
        ),
    ]
    for source, target in diagram.edges:
        path = _edge_path(source, target)
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in path)
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="#64748b" '
            'stroke-width="4" stroke-linejoin="round" marker-end="url(#arrow)"/>'
        )
    for node, box in BOXES.items():
        fill, stroke = _palette(node)
        parts.append(
            f'<rect x="{box.x}" y="{box.y}" width="{box.width}" height="{box.height}" '
            f'rx="18" fill="{fill}" stroke="{stroke}" stroke-width="4"/>'
        )
        lines = _wrapped_lines(diagram.labels[node])
        start_y = box.y + box.height / 2 - ((len(lines) - 1) * 18) + 9
        for index, line in enumerate(lines):
            y = start_y + index * 36
            parts.append(
                f'<text x="{box.x + box.width / 2:.1f}" y="{y:.1f}" text-anchor="middle" '
                'font-family="DejaVu Sans,Arial,sans-serif" font-size="23" '
                f'font-weight="700" fill="#172033">{html.escape(line)}</text>'
            )
    legend_y = 1290
    legends = (
        (60, "Compute", "#e8f2ff", "#2563eb"),
        (340, "Data/evidence", "#ecfdf5", "#059669"),
        (640, "Control/managed service", "#fff7ed", "#ea580c"),
        (1040, "Client", "#f8fafc", "#64748b"),
    )
    for x, label, fill, stroke in legends:
        parts.extend(
            (
                (
                    f'<rect x="{x}" y="{legend_y}" width="34" height="24" rx="5" '
                    f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
                ),
                (
                    f'<text x="{x + 46}" y="{legend_y + 20}" '
                    'font-family="DejaVu Sans,Arial,sans-serif" font-size="20" '
                    f'fill="#475569">{html.escape(label)}</text>'
                ),
            )
        )
    parts.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("portfolio/architecture.mmd"))
    parser.add_argument(
        "--svg", type=Path, default=Path("portfolio/assets/modelguard-architecture.svg")
    )
    parser.add_argument(
        "--png", type=Path, default=Path("portfolio/assets/modelguard-architecture.png")
    )
    return parser


def main() -> int:
    """Validate the fixed Mermaid graph and write both shareable formats."""

    args = _parser().parse_args()
    diagram = parse_mermaid(args.input)
    render_svg(diagram, args.svg)
    render_png(diagram, args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
