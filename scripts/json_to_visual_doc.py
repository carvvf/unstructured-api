#!/usr/bin/env python3
"""Convert analysis JSON into a human-friendly HTML report for visual comparison."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from html import escape as html_escape
import re
from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert the JSON produced by the Unstructured analysis pipeline into an "
            "HTML report that is easier to review alongside the original document."
        )
    )
    parser.add_argument(
        "json_path",
        type=Path,
        help="Path to the JSON file produced by the analysis pipeline.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "Destination path for the generated HTML report. Defaults to <json_path>.analysis.html "
            "for the summary view and <json_path>.layout.html for the layout view."
        ),
    )
    parser.add_argument(
        "--source-file",
        type=Path,
        help="Optional path to the original document. Added to the report for quick reference.",
    )
    parser.add_argument(
        "--title",
        type=str,
        help="Optional custom title for the report. Defaults to the JSON file name.",
    )
    parser.add_argument(
        "--view",
        choices=["summary", "layout", "svg"],
        default="summary",
        help=(
            "Choose the report style. 'summary' groups elements by page in reading order, "
            "'layout' replays the document via HTML, and 'svg' writes a vector layout preview."
        ),
    )
    return parser.parse_args()


def load_elements(json_path: Path) -> Sequence[Mapping[str, object]]:
    try:
        with json_path.open("r", encoding="utf-8") as infile:
            payload = json.load(infile)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Unable to parse JSON file {json_path}: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"Unable to read JSON file {json_path}: {exc}") from exc

    if isinstance(payload, Mapping):
        # Allow wrapping dictionaries that hold the elements list.
        payload = payload.get("elements", payload)

    if not isinstance(payload, Sequence):
        raise SystemExit(
            f"Expected JSON payload to be a list of elements, received {type(payload).__name__}"
        )

    return payload


TYPE_COLOR_OVERRIDES: dict[str, tuple[str, str]] = {
    "title": ("#1d4ed8", "rgba(29, 78, 216, 0.15)"),
    "narrativetext": ("#0f766e", "rgba(15, 118, 110, 0.16)"),
    "uncategorizedtext": ("#6b7280", "rgba(107, 114, 128, 0.18)"),
    "listitem": ("#7c3aed", "rgba(124, 58, 237, 0.18)"),
    "table": ("#d97706", "rgba(217, 119, 6, 0.16)"),
    "image": ("#db2777", "rgba(219, 39, 119, 0.16)"),
}

FONT_AREA_FACTOR = 4200.0
FONT_SCALE_MIN = 0.3
FONT_SCALE_MAX = 3.2
WIDTH_CHAR_DENOM = 18.0
HEIGHT_LINE_DENOM = 28.0


def color_for_type(element_type: str | None) -> tuple[str, str]:
    """Derive a pair of accent colors from the element type."""
    label = (element_type or "Unknown").strip() or "Unknown"
    override = TYPE_COLOR_OVERRIDES.get(label.lower())
    if override:
        return override

    hue = sum(ord(char) for char in label) % 360
    accent = f"hsl({hue}, 70%, 35%)"
    background = f"hsla({hue}, 85%, 88%, 0.85)"
    return accent, background


def _text_line_stats(text: str) -> tuple[int, int]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        stripped = text.strip()
        if not stripped:
            return 0, 0
        lines = [stripped]
    line_count = len(lines)
    width_chars = max(len(line) for line in lines)
    return line_count, width_chars


def estimate_font_scale(
    *,
    text: str,
    box_width: float,
    box_height: float,
    safe_width: float,
    safe_height: float,
) -> float | None:
    trimmed = text.strip()
    if not trimmed:
        return None

    line_count, width_chars = _text_line_stats(trimmed)
    if width_chars == 0:
        width_chars = len(trimmed)
    if width_chars == 0:
        return None

    area_ratio = max(1e-6, (box_width * box_height) / (safe_width * safe_height))
    density_scale = (area_ratio * FONT_AREA_FACTOR) / max(1, len(trimmed))

    width_scale = (box_width / max(4, width_chars)) / WIDTH_CHAR_DENOM
    height_scale = (box_height / max(1, line_count)) / HEIGHT_LINE_DENOM

    scale = min(width_scale, height_scale)
    if density_scale > 0:
        scale = max(scale, density_scale * 0.7)

    if scale <= 0:
        return None

    return max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale))


def sanitise_metadata(metadata: object) -> str:
    """Render metadata as a JSON block suitable for embedding in HTML."""
    try:
        metadata_json = json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False)
    except TypeError:
        metadata_json = repr(metadata)
    return html_escape(metadata_json)


def grouped_by_page(elements: Sequence[Mapping[str, object]]):
    grouped = defaultdict(list)
    for element in elements:
        metadata = element.get("metadata") if isinstance(element, Mapping) else None
        page_number = None

        if isinstance(metadata, Mapping):
            page_number = metadata.get("page_number") or metadata.get("page")

        page_key = "unknown" if page_number in (None, "", []) else str(page_number)
        grouped[page_key].append(element)

    def page_sort_key(entry: tuple[str, list[Mapping[str, object]]]) -> tuple[int, str]:
        page_label = entry[0]
        try:
            return (0, f"{int(page_label):06d}")
        except ValueError:
            return (1, page_label)

    return dict(sorted(grouped.items(), key=page_sort_key))


def element_type(element: Mapping[str, object]) -> str:
    return str(element.get("type") or "Unknown")


def element_text(element: Mapping[str, object]) -> str:
    text = element.get("text")
    if text is None:
        return ""
    return str(text)


def metadata_block(element: Mapping[str, object]) -> str:
    metadata = element.get("metadata")
    rendered = sanitise_metadata(metadata)
    return f"<details><summary>Metadata</summary><pre>{rendered}</pre></details>"


def as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def extract_box(coordinates: Mapping[str, object] | None) -> dict[str, float | str | None] | None:
    if not isinstance(coordinates, Mapping):
        return None

    points = coordinates.get("points")
    xs: list[float] = []
    ys: list[float] = []

    if isinstance(points, Sequence):
        for point in points:
            if isinstance(point, Mapping):
                x_val = as_float(point.get("x") or point.get("X"))
                y_val = as_float(point.get("y") or point.get("Y"))
            elif isinstance(point, Sequence) and len(point) >= 2:
                x_val = as_float(point[0])
                y_val = as_float(point[1])
            else:
                x_val = None
                y_val = None

            if x_val is not None and y_val is not None:
                xs.append(x_val)
                ys.append(y_val)

    if not xs or not ys:
        return None

    left = min(xs)
    right = max(xs)
    top = min(ys)
    bottom = max(ys)

    layout_width = as_float(coordinates.get("layout_width"))
    layout_height = as_float(coordinates.get("layout_height"))
    system = coordinates.get("system")

    width = max(right - left, 0.0)
    height = max(bottom - top, 0.0)

    return {
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "width": width,
        "height": height,
        "layout_width": layout_width,
        "layout_height": layout_height,
        "system": system if isinstance(system, str) else None,
    }


def image_scale_for_ratio(ratio: float | None) -> float:
    if ratio is None or ratio <= 0:
        return 1.0

    ratio = max(0.05, min(ratio, 50.0))

    if 0.7 <= ratio <= 1.4:
        return 6.0
    if 0.5 <= ratio < 0.7 or 1.4 < ratio <= 2.5:
        return 4.0
    if 0.33 <= ratio < 0.5 or 2.5 < ratio <= 4.0:
        return 3.0
    if 0.2 <= ratio < 0.33 or 4.0 < ratio <= 6.0:
        return 2.0
    return 1.6


def trim_image_base64(image_base64: str) -> tuple[str, tuple[int, int] | None]:
    """Trim empty margins from a base64 image if Pillow is available.

    Returns the (possibly unchanged) base64 string and the trimmed dimensions,
    which can be used to derive a more accurate aspect ratio.
    """
    try:
        from PIL import Image, ImageOps, ImageChops
    except ImportError:
        base_repo = Path(__file__).resolve().parents[1]
        workspace_root = base_repo.parent
        candidate_roots = [
            base_repo / "uapi_venv_cpu/lib/python3.12/site-packages",
            base_repo / "uapi_venv/lib/python3.12/site-packages",
            workspace_root / "uapi_venv_cpu/lib/python3.12/site-packages",
            workspace_root / "uapi_venv/lib/python3.12/site-packages",
        ]
        inserted = False
        for root in candidate_roots:
            if root.exists() and str(root) not in sys.path:
                sys.path.insert(0, str(root))
                inserted = True
        if inserted:
            try:
                from PIL import Image, ImageOps, ImageChops  # type: ignore[redefinition]
            except ImportError:
                return image_base64, None
        else:
            return image_base64, None

    try:
        binary = base64.b64decode(image_base64)
    except (ValueError, binascii.Error):  # type: ignore[name-defined]
        return image_base64, None

    try:
        with Image.open(BytesIO(binary)) as img:
            img = img.convert("RGBA")
            width, height = img.size
            bbox: tuple[int, int, int, int] | None = None

            # Attempt to use the alpha channel when present.
            alpha = img.split()[-1]
            if alpha.getextrema() != (255, 255):
                bbox = alpha.getbbox()

            gray = ImageOps.grayscale(img)

            if not bbox or bbox == (0, 0, width, height):
                # Highlight darker pixels; anything near pure white is treated as margin.
                high_contrast = gray.point(lambda px: 255 if px < 245 else 0, "1")
                candidate = high_contrast.getbbox()
                if candidate:
                    bbox = candidate  # type: ignore[assignment]

            if not bbox or bbox == (0, 0, width, height):
                # Fall back to looking for differences from a sampled background shade.
                corners = [
                    gray.getpixel((0, 0)),
                    gray.getpixel((width - 1, 0)),
                    gray.getpixel((0, height - 1)),
                    gray.getpixel((width - 1, height - 1)),
                ]
                background_value = int(sum(corners) / len(corners))
                background = Image.new("L", gray.size, background_value)
                diff = ImageChops.difference(gray, background)
                mask = diff.point(lambda px: 255 if px > 6 else 0, "1")
                candidate = mask.getbbox()
                if candidate:
                    bbox = candidate  # type: ignore[assignment]

            if not bbox:
                return image_base64, (width, height)

            left, top, right, bottom = bbox
            padding = max(1, int(min(width, height) * 0.01))
            left = max(0, left - padding)
            top = max(0, top - padding)
            right = min(width, right + padding)
            bottom = min(height, bottom + padding)

            if right <= left or bottom <= top:
                return image_base64, (width, height)

            cropped = img.crop((left, top, right, bottom))
            with BytesIO() as bio:
                cropped.save(bio, format="PNG")
                trimmed = base64.b64encode(bio.getvalue()).decode("ascii")
            return trimmed, (cropped.width, cropped.height)
    except Exception:
        return image_base64, None


def resolve_page_dimensions(page_elements: Sequence[Mapping[str, object]]) -> tuple[float, float]:
    layout_width: float | None = None
    layout_height: float | None = None
    max_right: float | None = None
    max_bottom: float | None = None
    system: str | None = None

    for element in page_elements:
        metadata = element.get("metadata")
        coordinates = None
        if isinstance(metadata, Mapping):
            coordinates = metadata.get("coordinates")
        box = extract_box(coordinates) if isinstance(coordinates, Mapping) else None
        if not box:
            continue

        system = system or (box.get("system") if isinstance(box.get("system"), str) else None)
        if box.get("layout_width"):
            layout_width = box["layout_width"]  # type: ignore[assignment]
        if box.get("layout_height"):
            layout_height = box["layout_height"]  # type: ignore[assignment]

        max_right = max(max_right or 0.0, float(box["right"]))  # type: ignore[arg-type]
        max_bottom = max(max_bottom or 0.0, float(box["bottom"]))  # type: ignore[arg-type]

    if layout_width and layout_height:
        return layout_width, layout_height

    if system and system.lower().startswith("normalized"):
        return 1.0, 1.0

    if max_right and max_bottom:
        return max_right, max_bottom

    return 1.0, 1.0


def build_layout_html(
    *,
    title: str,
    json_path: Path,
    elements: Sequence[Mapping[str, object]],
    source_path: Path | None,
) -> str:
    grouped = grouped_by_page(elements)
    page_dimensions: dict[str, tuple[float, float]] = {
        label: resolve_page_dimensions(page_elems) for label, page_elems in grouped.items()
    }
    type_palette: dict[str, tuple[str, str]] = {}

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_info = ""
    if source_path:
        source_info = (
            f'<p class="source">Original file: <code>{html_escape(str(source_path))}</code></p>'
        )

    page_sections: list[str] = []
    missing_coordinates: list[tuple[str, Mapping[str, object]]] = []

    for page_label, page_elements in grouped.items():
        width, height = page_dimensions.get(page_label, (1.0, 1.0))
        safe_width = width if width > 0 else 1.0
        safe_height = height if height > 0 else 1.0
        section_parts = [f'<section class="page" id="layout-page-{html_escape(page_label)}">']
        section_parts.append(f"<h2>Page {html_escape(page_label)}</h2>")
        section_parts.append(
            (
                '<div class="page-frame" style="--page-width:{width}; --page-height:{height}; '
                '--aspect-ratio:{ratio};">'
                '<div class="page-canvas">'
            ).format(width=safe_width, height=safe_height, ratio=safe_width / safe_height)
        )

        for element in page_elements:
            metadata = element.get("metadata") if isinstance(element, Mapping) else None
            coordinates = None
            if isinstance(metadata, Mapping):
                coordinates = metadata.get("coordinates")
            box = extract_box(coordinates) if isinstance(coordinates, Mapping) else None
            if not box:
                missing_coordinates.append((page_label, element))
                continue

            left = float(box["left"]) if box.get("left") is not None else 0.0
            top = float(box["top"]) if box.get("top") is not None else 0.0
            box_width = float(box["width"]) if box.get("width") is not None else 0.0
            box_height = float(box["height"]) if box.get("height") is not None else 0.0

            left_pct = f"{(left / safe_width) * 100:.4f}%"
            top_pct = f"{(top / safe_height) * 100:.4f}%"
            width_pct = f"{max(box_width, 0.1) / safe_width * 100:.4f}%"
            height_pct = f"{max(box_height, 0.1) / safe_height * 100:.4f}%"

            el_type = element_type(element)
            accent, background = color_for_type(el_type)
            type_palette.setdefault(el_type, (accent, background))
            box_classes = ["box"]

            metadata = element.get("metadata") if isinstance(element, Mapping) else None
            table_html: str | None = None
            has_table_html = False
            if el_type.lower() == "table" and isinstance(metadata, Mapping):
                table_candidate = metadata.get("text_as_html")
                if isinstance(table_candidate, str) and table_candidate.strip():
                    table_html = table_candidate
                    has_table_html = True
                    box_classes.append("table-box")

            image_html: str | None = None
            image_scale = 1.0
            image_fit = "contain"
            if isinstance(metadata, Mapping) and el_type.lower() != "table":
                image_base64 = metadata.get("image_base64")
                if isinstance(image_base64, str) and image_base64.strip():
                    image_mime = metadata.get("image_mime_type")
                    if not isinstance(image_mime, str) or not image_mime:
                        image_mime = "image/png"
                    trimmed_base64, trimmed_dims = trim_image_base64(image_base64)
                    image_data = "".join(trimmed_base64.split())
                    ratio = None
                    if trimmed_dims:
                        trimmed_width, trimmed_height = trimmed_dims
                        if trimmed_height:
                            ratio = trimmed_width / trimmed_height
                    if ratio is None and box_height and box_height > 0:
                        ratio = box_width / box_height if box_width else None
                    image_scale = image_scale_for_ratio(ratio)
                    if ratio is not None and 0.65 <= ratio <= 1.5:
                        image_fit = "cover"
                    image_html = (
                        '<figure class="image-content">'
                        '<img src="data:{mime};base64,{data}" alt="{alt}" loading="lazy" />'
                        "</figure>"
                    ).format(
                        mime=html_escape(image_mime),
                        data=image_data,
                        alt=html_escape(f"{el_type} element"),
                    )
                    box_classes.append("image-box")

            font_scale: float | None = None

            if image_html:
                content_block = image_html
            elif has_table_html and table_html:
                content_block = f'<div class="table-content">{table_html}</div>'
                plain_text = re.sub(r"<[^>]+>", "", table_html)
                font_scale = estimate_font_scale(
                    text=plain_text,
                    box_width=box_width,
                    box_height=box_height,
                    safe_width=safe_width,
                    safe_height=safe_height,
                )
            else:
                text_value = element_text(element)
                content_block = f'<div class="text">{html_escape(text_value)}</div>'
                font_scale = estimate_font_scale(
                    text=text_value,
                    box_width=box_width,
                    box_height=box_height,
                    safe_height=safe_height,
                    safe_width=safe_width,
                )

            style_parts = [
                f"left:{left_pct}",
                f"top:{top_pct}",
                f"width:{width_pct}",
                f"height:{height_pct}",
                f"border-color:{accent}",
                f"background-color:{background}",
                f"--image-scale:{image_scale}",
                f"--image-fit:{image_fit}",
            ]

            if font_scale is not None:
                style_parts.append(f"--font-scale:{font_scale:.3f}rem")

            section_parts.append(
                (
                    '<article class="{classes}" data-type="{el_type}" title="{el_type}" style="{style_attr};">'
                    '{content_block}'
                    "</article>"
                ).format(
                    classes=" ".join(box_classes),
                    el_type=html_escape(el_type),
                    style_attr="; ".join(style_parts),
                    content_block=content_block,
                )
            )

        section_parts.append("</div></div></section>")
        page_sections.append("\n".join(section_parts))

    missing_section = ""
    if missing_coordinates:
        items = []
        for page_label, element in missing_coordinates:
            el_type = element_type(element)
            text_preview = element_text(element)[:120]
            items.append(
                "<li><strong>Page {page}</strong> · {etype} · {text}</li>".format(
                    page=html_escape(page_label),
                    etype=html_escape(el_type),
                    text=html_escape(text_preview or "(no text)"),
                )
            )
        missing_section = (
            "<section class=\"no-coords\">"
            "<h2>Elements without coordinates</h2>"
            "<ul>{items}</ul>"
            "</section>".format(items="\n".join(items))
        )

    legend_section = ""
    if type_palette:
        legend_items = "\n".join(
            (
                '<li><span class="dot" style="--legend-color:{accent}; --legend-background:{background};"></span>'
                "{label}</li>"
            ).format(
                accent=html_escape(accent),
                background=html_escape(background),
                label=html_escape(label or "Unknown"),
            )
            for label, (accent, background) in sorted(type_palette.items(), key=lambda item: item[0])
        )
        legend_section = (
            '<section class="legend"><h3>Legenda tipologie</h3><ul>{items}</ul></section>'.format(
                items=legend_items
            )
        )

    template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
    }}
    body {{
      margin: 0;
      padding: 1.5rem 2rem 3rem;
      background-color: #f4f6f8;
      color: #1f2933;
    }}
    header.report-header {{
      margin-bottom: 2rem;
    }}
    header.report-header h1 {{
      margin: 0;
      font-size: 1.6rem;
    }}
    header.report-header p {{
      margin: 0.25rem 0 0;
      color: #4b5563;
    }}
    .source {{
      margin: 0.5rem 0 0;
      font-size: 0.85rem;
      color: #4b5563;
    }}
    section.page {{
      margin: 2rem auto;
      max-width: min(960px, 95vw);
      background: #ffffff;
      border-radius: 1rem;
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
      padding: 1.25rem 1.5rem 1.75rem;
    }}
    section.page h2 {{
      margin: 0 0 1rem;
      font-size: 1.1rem;
      border-bottom: 1px solid #e5e7eb;
      padding-bottom: 0.5rem;
    }}
    .page-frame {{
      position: relative;
      width: 100%;
      aspect-ratio: var(--aspect-ratio, 1 / 1);
      background: repeating-linear-gradient(
        45deg,
        rgba(148, 163, 184, 0.06),
        rgba(148, 163, 184, 0.06) 12px,
        rgba(148, 163, 184, 0.12) 12px,
        rgba(148, 163, 184, 0.12) 24px
      );
      border: 1px solid rgba(15, 23, 42, 0.12);
      border-radius: 0.75rem;
      overflow: hidden;
    }}
    .page-canvas {{
      position: absolute;
      inset: 0;
    }}
    article.box {{
      position: absolute;
      box-sizing: border-box;
      border: 2px solid;
      background-color: rgba(255, 255, 255, 0.82);
      border-radius: 0.5rem;
      padding: 0.35rem 0.45rem;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      overflow: hidden;
    }}
    article.box .text {{
      font-size: var(--font-scale, 0.95rem);
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
      color: #1f2937;
    }}
    article.box.image-box {{
      padding: 0;
      gap: 0;
    }}
    .image-content {{
      flex: 1;
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }}
    .image-content img {{
      width: 100%;
      height: 100%;
      object-fit: var(--image-fit, contain);
      display: block;
      transform: scale(var(--image-scale, 1.25));
      transform-origin: center;
    }}
    .table-content {{
      height: 100%;
      overflow: auto;
      padding: 0.2rem;
      box-sizing: border-box;
      font-size: var(--font-scale, 0.92rem);
    }}
    .table-content table {{
      width: 100%;
      border-collapse: collapse;
      font-size: inherit;
    }}
    .table-content td,
    .table-content th {{
      border: 1px solid rgba(148, 163, 184, 0.6);
      padding: 0.15rem 0.3rem;
      text-align: left;
    }}
    .table-content th {{
      background: rgba(37, 99, 235, 0.12);
      font-weight: 600;
    }}
    .legend {{
      margin: 0 auto 1.75rem;
      max-width: min(960px, 95vw);
      padding: 0.9rem 1.1rem;
      background: #ffffff;
      border-radius: 1rem;
      box-shadow: 0 12px 28px rgba(15, 23, 42, 0.12);
    }}
    .legend h3 {{
      margin: 0 0 0.75rem;
      font-size: 0.95rem;
      color: #1f2937;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .legend ul {{
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      gap: 0.65rem 1rem;
      margin: 0;
      padding: 0;
    }}
    .legend li {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.85rem;
      padding: 0.35rem 0.75rem;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.04);
      box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.28);
    }}
    .legend .dot {{
      display: inline-block;
      width: 0.7rem;
      height: 0.7rem;
      border-radius: 50%;
      background: var(--legend-color);
      box-shadow: 0 0 0 4px var(--legend-background);
    }}
    .no-coords {{
      max-width: min(960px, 95vw);
      margin: 2rem auto 0;
      padding: 1.25rem 1.5rem;
      background: #ffffff;
      border-radius: 1rem;
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.16);
    }}
    .no-coords h2 {{
      margin: 0 0 0.75rem;
      font-size: 1.05rem;
    }}
    .no-coords ul {{
      margin: 0;
      padding-left: 1.1rem;
      color: #374151;
      line-height: 1.5;
    }}
    @media (max-width: 720px) {{
      body {{
        padding: 1.25rem;
      }}
      section.page {{
        padding: 1rem 1.1rem 1.4rem;
      }}
      .legend {{
        padding: 0.75rem 0.9rem;
      }}
      .legend ul {{
        gap: 0.55rem 0.75rem;
      }}
    }}
  </style>
</head>
<body>
  <header class="report-header">
    <h1>{html_escape(title)}</h1>
    <p>Generated on {html_escape(now_str)} from <code>{html_escape(str(json_path))}</code>.</p>
    {source_info}
  </header>
  {legend_section}
  {''.join(page_sections)}
  {missing_section}
</body>
</html>
"""
    return template


SVG_PAGE_GAP = 140.0
SVG_FONT_COLOR = "#111827"


def build_layout_svg(
    *,
    title: str,
    json_path: Path,
    elements: Sequence[Mapping[str, object]],
    source_path: Path | None,
) -> str:
    grouped = grouped_by_page(elements)
    page_dimensions: dict[str, tuple[float, float]] = {
        label: resolve_page_dimensions(page_elems) for label, page_elems in grouped.items()
    }
    if not page_dimensions:
        page_dimensions["1"] = (1000.0, 1414.0)

    positions: list[tuple[str, list[Mapping[str, object]], float, float, float]] = []
    y_offset = 0.0
    max_width = 0.0
    for label, page_elements in grouped.items():
        width, height = page_dimensions.get(label, (1000.0, 1414.0))
        positions.append((label, page_elements, width, height, y_offset))
        max_width = max(max_width, width)
        y_offset += height + SVG_PAGE_GAP

    if not positions:
        width, height = page_dimensions["1"]
        positions.append(("1", [], width, height, 0.0))
        max_width = max(max_width, width)
        y_offset = height

    total_height = y_offset - SVG_PAGE_GAP if positions else 0.0
    total_height = max(total_height, 1.0)
    total_width = max(max_width, 1.0)

    header_y = 60.0

    svg_parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_width:.2f}" height="{total_height + header_y:.2f}" '
        f'viewBox="0 0 {total_width:.2f} {total_height + header_y:.2f}">',
        '<style>',
        "  text { font-family: 'Inter', 'Segoe UI', sans-serif; fill: #111827; }",
        "  .page-header { font-size: 28px; font-weight: 600; fill: #0f172a; }",
        "  .element-label { font-size: 22px; fill: #334155; font-weight: 600; }",
        "  .table-html { font-family: 'Inter', 'Segoe UI', sans-serif; color: #1f2937; }",
        "  .table-html table { width: 100%; border-collapse: collapse; }",
        "  .table-html td, .table-html th { border: 1px solid rgba(148, 163, 184, 0.55); padding: 4px 6px; text-align: left; }",
        "</style>",
        f'<text x="{20:.2f}" y="{header_y/2:.2f}" class="page-header">'
        f"{html_escape(title)} – {html_escape(str(json_path.name))}</text>",
    ]

    for index, (page_label, page_elements, width, height, offset) in enumerate(positions):
        base_y = offset + header_y
        svg_parts.append(
            (
                f'<g id="page-{html_escape(page_label)}" transform="translate(0,{base_y:.2f})">'
                f'<rect x="0" y="0" width="{width:.2f}" height="{height:.2f}" '
                'fill="#f8fafc" stroke="#d0d7de" stroke-width="1.0"/>'
                f'<text x="{20:.2f}" y="{40:.2f}" class="element-label">Page {html_escape(page_label)}</text>'
            )
        )

        safe_width = width
        safe_height = height

        for element in page_elements:
            el_type = element_type(element)
            accent, background = color_for_type(el_type)
            data = element.get("metadata") if isinstance(element, Mapping) else None
            box = extract_box(data.get("coordinates") if isinstance(data, Mapping) else None)
            if not box:
                continue

            left = float(box["left"]) if box.get("left") is not None else 0.0
            top = float(box["top"]) if box.get("top") is not None else 0.0
            box_width = float(box["width"]) if box.get("width") is not None else 0.0
            box_height = float(box["height"]) if box.get("height") is not None else 0.0

            element_parts = [
                f'<g class="element" data-type="{html_escape(el_type)}" transform="translate(0,0)">',
                f'<rect x="{left:.2f}" y="{top:.2f}" width="{box_width:.2f}" height="{box_height:.2f}" '
                f'rx="18" ry="18" fill="{background}" stroke="{accent}" stroke-width="3"/>',
            ]

            metadata = element.get("metadata") if isinstance(element, Mapping) else None
            table_html = None
            if el_type.lower() == "table" and isinstance(metadata, Mapping):
                candidate = metadata.get("text_as_html")
                if isinstance(candidate, str) and candidate.strip():
                    table_html = candidate

            image_data: str | None = None
            image_fit = "meet"
            if isinstance(metadata, Mapping):
                image_base64 = metadata.get("image_base64")
                if isinstance(image_base64, str) and image_base64.strip():
                    trimmed_base64, trimmed_dims = trim_image_base64(image_base64)
                    ratio = None
                    if trimmed_dims:
                        tw, th = trimmed_dims
                        if th:
                            ratio = tw / th
                    if ratio is None and box_height > 0:
                        ratio = box_width / box_height if box_width else None
                    image_fit = "slice" if ratio and 0.65 <= ratio <= 1.5 else "meet"
                    image_data = trimmed_base64

            if image_data:
                preserve = "xMidYMid slice" if image_fit == "slice" else "xMidYMid meet"
                element_parts.append(
                    '<image '
                    f'x="{left:.2f}" y="{top:.2f}" width="{box_width:.2f}" height="{box_height:.2f}" '
                    f'preserveAspectRatio="{preserve}" '
                    f'href="data:image/png;base64,{image_data}"/>'
                )
            elif table_html:
                plain_text = re.sub(r"<[^>]+>", "", table_html)
                font_scale = estimate_font_scale(
                    text=plain_text,
                    box_width=box_width,
                    box_height=box_height,
                    safe_width=safe_width,
                    safe_height=safe_height,
                )
                font_px = (font_scale or 0.92) * 16.0
                element_parts.append(
                    (
                        '<foreignObject x="{left:.2f}" y="{top:.2f}" '
                        'width="{width:.2f}" height="{height:.2f}">' 
                        '<div xmlns="http://www.w3.org/1999/xhtml" class="table-html" '
                        'style="width:100%; height:100%; overflow:auto; font-size:{font_px:.2f}px; line-height:1.35;">'
                        '{table_html}'
                        '</div></foreignObject>'
                    ).format(
                        left=left,
                        top=top,
                        width=box_width,
                        height=box_height,
                        font_px=font_px,
                        table_html=table_html,
                    )
                )
            else:
                raw_text = element_text(element)
                font_scale = estimate_font_scale(
                    text=raw_text,
                    box_width=box_width,
                    box_height=box_height,
                    safe_width=safe_width,
                    safe_height=safe_height,
                )
                font_px = (font_scale or 0.92) * 16.0
                line_height = font_px * 1.25
                padding = min(box_width * 0.06, 18.0)
                x_start = left + padding
                y_start = top + padding
                lines = raw_text.splitlines() if raw_text else []
                if not lines:
                    lines = [raw_text]

                text_parts = [
                    f'<text x="{x_start:.2f}" y="{y_start:.2f}" '
                    f'font-size="{font_px:.2f}" fill="{SVG_FONT_COLOR}" '
                    'font-family="Inter, Segoe UI, sans-serif">'
                ]
                for idx, line in enumerate(lines):
                    safe_line = html_escape(line)
                    text_parts.append(
                        f'<tspan x="{x_start:.2f}" y="{y_start + idx * line_height:.2f}">{safe_line}</tspan>'
                    )
                text_parts.append("</text>")
                element_parts.extend(text_parts)

            element_parts.append("</g>")
            svg_parts.extend(element_parts)

        svg_parts.append("</g>")

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def build_report_html(
    *,
    title: str,
    json_path: Path,
    elements: Sequence[Mapping[str, object]],
    source_path: Path | None,
) -> str:
    type_counts = Counter(element_type(elem) for elem in elements)
    total_text = sum(len(element_text(elem)) for elem in elements)
    grouped = grouped_by_page(elements)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_info = ""
    if source_path:
        source_info = (
            f'<p class="source">Original file: <code>{html_escape(str(source_path))}</code></p>'
        )

    header_counts = "\n".join(
        f'<li><span class="badge">{count}</span> {html_escape(elem_type)}</li>'
        for elem_type, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
    )

    page_sections = []
    for page_label, page_elements in grouped.items():
        page_header = f"Page {page_label}" if page_label != "unknown" else "Page unknown"
        section_parts = [f'<section class="page" id="page-{html_escape(page_label)}">']
        section_parts.append(f"<h2>{html_escape(page_header)}</h2>")

        for idx, element in enumerate(page_elements, start=1):
            el_type = element_type(element)
            el_text = html_escape(element_text(element))
            accent, background = color_for_type(el_type)
            details = metadata_block(element)
            section_parts.append(
                (
                    '<article class="element" style="--accent-color: {accent};'
                    ' --accent-background: {background};">'
                    "<header><span class=\"element-type\">{el_type}</span>"
                    "<span class=\"element-order\">#{idx}</span>"
                    "</header><pre class=\"element-text\">{el_text}</pre>{details}</article>"
                ).format(
                    accent=accent,
                    background=background,
                    el_type=html_escape(el_type),
                    idx=idx,
                    el_text=el_text,
                    details=details,
                )
            )

        section_parts.append("</section>")
        page_sections.append("\n".join(section_parts))

    template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
    }}
    body {{
      margin: 0;
      padding: 1.5rem 2rem 3rem;
      background-color: #f4f6f8;
      color: #1f2933;
    }}
    header.report-header {{
      margin-bottom: 2rem;
    }}
    header.report-header h1 {{
      margin: 0;
      font-size: 1.6rem;
    }}
    header.report-header p {{
      margin: 0.25rem 0 0;
      color: #4b5563;
    }}
    .summary {{
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      margin-top: 1rem;
      padding: 1rem;
      background: #ffffff;
      border-radius: 0.75rem;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.12);
    }}
    .summary .stat {{
      min-width: 9rem;
    }}
    .summary .stat-label {{
      font-size: 0.8rem;
      color: #6b7280;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      display: block;
    }}
    .summary .stat-value {{
      font-size: 1.2rem;
      font-weight: 600;
      color: #111827;
    }}
    .type-counts {{
      margin: 1.5rem 0 0;
      padding: 0;
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
    }}
    .type-counts li {{
      background: #ffffff;
      border-radius: 999px;
      padding: 0.35rem 0.85rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.85rem;
      box-shadow: 0 6px 15px rgba(15, 23, 42, 0.08);
    }}
    .badge {{
      background: #111827;
      color: #ffffff;
      border-radius: 999px;
      padding: 0.15rem 0.6rem;
      font-weight: 600;
      font-size: 0.8rem;
    }}
    .source {{
      margin: 0.5rem 0 0;
      font-size: 0.85rem;
      color: #4b5563;
    }}
    section.page {{
      margin-top: 2rem;
      padding: 1.5rem;
      background: #ffffff;
      border-radius: 1rem;
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
    }}
    section.page h2 {{
      margin-top: 0;
      border-bottom: 1px solid #e5e7eb;
      padding-bottom: 0.6rem;
      font-size: 1.1rem;
    }}
    article.element {{
      margin-top: 1.25rem;
      padding: 1rem 1.25rem;
      border-radius: 0.9rem;
      border-left: 6px solid var(--accent-color, #2563eb);
      background: var(--accent-background, rgba(37, 99, 235, 0.12));
      box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.04);
    }}
    article.element header {{
      display: flex;
      align-items: baseline;
      gap: 0.75rem;
    }}
    .element-type {{
      font-weight: 600;
      font-size: 0.95rem;
      color: #111827;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .element-order {{
      font-size: 0.8rem;
      color: #4b5563;
    }}
    pre.element-text {{
      margin: 0.75rem 0 0;
      padding: 0.75rem;
      background: rgba(255, 255, 255, 0.65);
      border-radius: 0.65rem;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 0.95rem;
      line-height: 1.6;
    }}
    details {{
      margin-top: 0.6rem;
      font-size: 0.85rem;
    }}
    details pre {{
      margin-top: 0.4rem;
      padding: 0.6rem;
      border-radius: 0.5rem;
      background: #111827;
      color: #f9fafb;
      overflow-x: auto;
    }}
    @media (max-width: 720px) {{
      body {{
        padding: 1.25rem;
      }}
      section.page {{
        padding: 1.15rem;
      }}
      article.element {{
        padding: 0.85rem;
      }}
    }}
  </style>
</head>
<body>
  <header class="report-header">
    <h1>{html_escape(title)}</h1>
    <p>Generated on {html_escape(now_str)} from <code>{html_escape(str(json_path))}</code>.</p>
    {source_info}
    <div class="summary">
      <div class="stat">
        <span class="stat-label">Elements</span>
        <span class="stat-value">{len(elements)}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Pages</span>
        <span class="stat-value">{len(grouped)}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Total characters</span>
        <span class="stat-value">{total_text}</span>
      </div>
    </div>
    <ul class="type-counts">
      {header_counts}
    </ul>
  </header>
  {''.join(page_sections)}
</body>
</html>
"""
    return template


def default_output_path(json_path: Path, view: str) -> Path:
    base = json_path.with_suffix("")
    if view == "summary":
        suffix = ".analysis.html"
    elif view == "layout":
        suffix = ".layout.html"
    else:
        suffix = ".layout.svg"
    return base.parent / f"{base.name}{suffix}"


def main() -> int:
    args = parse_args()

    if not args.json_path.exists():
        print(f"JSON file not found: {args.json_path}", file=sys.stderr)
        return 1

    elements = load_elements(args.json_path)
    output_path = args.output or default_output_path(args.json_path, args.view)
    title = args.title or args.json_path.name

    if args.view == "layout":
        report_html = build_layout_html(
            title=title,
            json_path=args.json_path,
            elements=elements,
            source_path=args.source_file,
        )
    elif args.view == "svg":
        report_html = build_layout_svg(
            title=title,
            json_path=args.json_path,
            elements=elements,
            source_path=args.source_file,
        )
    else:
        report_html = build_report_html(
            title=title,
            json_path=args.json_path,
            elements=elements,
            source_path=args.source_file,
        )

    try:
        output_path.write_text(report_html, encoding="utf-8")
    except OSError as exc:
        print(f"Unable to write report to {output_path}: {exc}", file=sys.stderr)
        return 1

    print(f"Report written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
    legend_section = ""
    if type_palette:
        legend_items = "\n".join(
            (
                '<li><span class="dot" style="--legend-color:{accent}; --legend-background:{background};"></span>'
                "{label}</li>"
            ).format(
                accent=html_escape(accent),
                background=html_escape(background),
                label=html_escape(label or "Unknown"),
            )
            for label, (accent, background) in sorted(type_palette.items(), key=lambda item: item[0])
        )
        legend_section = (
            '<section class="legend"><h3>Legenda tipologie</h3><ul>{items}</ul></section>'.format(
                items=legend_items
            )
        )
