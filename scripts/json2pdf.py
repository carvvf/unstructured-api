#!/usr/bin/env python3
"""Render layout JSON into a PDF preview with coordinate-aware placement."""

from __future__ import annotations

import argparse
import base64
import binascii
import math
import sys
from html import escape, unescape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re
from typing import Mapping, Sequence

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

try:
    from reportlab.platypus import Paragraph, Table, TableStyle
except ImportError as exc:
    raise SystemExit("ReportLab is required. Install via `pip install reportlab`.") from exc

from json_to_visual_doc import (
    color_for_type,
    estimate_font_scale,
    extract_box,
    grouped_by_page,
    resolve_page_dimensions,
    load_elements,
    element_text,
    element_type,
)


DEFAULT_PAGE_WIDTH = A4[0]  # 595pt
DEFAULT_MARGIN = 36.0


class HTMLTableParser(HTMLParser):
    """Extract text and colspan information from a simple HTML table snippet."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict[str, str | int]]] = []
        self._current_row: list[dict[str, str | int]] | None = None
        self._current_cell: dict[str, str | int] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th") and self._current_row is not None:
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            colspan = int(attr_dict.get("colspan", "1") or "1")
            self._current_cell = {"text": "", "colspan": max(1, colspan)}

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None
        elif tag in ("td", "th") and self._current_cell is not None and self._current_row is not None:
            text = self._current_cell.get("text", "")
            self._current_cell["text"] = unescape(str(text).strip())
            self._current_row.append(self._current_cell)
            self._current_cell = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            existing = str(self._current_cell.get("text", ""))
            self._current_cell["text"] = existing + data


def parse_table_html(html: str) -> tuple[list[list[str]], list[tuple[int, int, int]], list[float]]:
    parser = HTMLTableParser()
    parser.feed(html)
    rows = parser.rows
    if not rows:
        return [], [], []

    col_count = max(sum(int(cell.get("colspan", 1)) for cell in row) for row in rows)
    data: list[list[str]] = [["" for _ in range(col_count)] for _ in range(len(rows))]
    spans: list[tuple[int, int, int]] = []
    column_weights: list[float] = [0.0 for _ in range(col_count)]

    for row_index, row in enumerate(rows):
        col_index = 0
        for cell in row:
            text = str(cell.get("text", "")).strip()
            colspan = int(cell.get("colspan", 1) or 1)
            weight = max(1.0, len(re.sub(r"\s+", "", text)) or len(text) or 1)

            while col_index < col_count and data[row_index][col_index]:
                col_index += 1

            if col_index >= col_count:
                break

            data[row_index][col_index] = text
            if colspan > 1:
                end_col = min(col_count - 1, col_index + colspan - 1)
                spans.append((row_index, col_index, end_col))
                for filler in range(col_index + 1, end_col + 1):
                    data[row_index][filler] = ""
                share = weight / max(1, colspan)
                for offset in range(colspan):
                    target = col_index + offset
                    if target < col_count:
                        column_weights[target] += share
                col_index = end_col
            else:
                column_weights[col_index] += weight
            col_index += 1

    for idx in range(len(column_weights)):
        if column_weights[idx] <= 0:
            column_weights[idx] = 1.0

    return data, spans, column_weights


def parse_color(color: str) -> Color:
    tentative = color.strip()
    if tentative.startswith("#"):
        return HexColor(tentative)
    if tentative.startswith("rgba") or tentative.startswith("rgb"):
        start = tentative.find("(")
        end = tentative.rfind(")")
        if start != -1 and end != -1 and end > start:
            parts = [p.strip() for p in tentative[start + 1 : end].split(",")]
            try:
                r = int(float(parts[0]))
                g = int(float(parts[1]))
                b = int(float(parts[2]))
                alpha = float(parts[3]) if len(parts) > 3 else 1.0
                return Color(r / 255.0, g / 255.0, b / 255.0, alpha)
            except (ValueError, IndexError):
                pass
    return HexColor("#4b5563")


def draw_wrapped_text(
    canv: canvas.Canvas,
    *,
    x: float,
    y_bottom: float,
    width: float,
    height: float,
    text: str,
    font_pts: float,
    line_color: Color,
) -> None:
    font_name = "Helvetica"
    line_spacing = font_pts * 1.25
    lines = simpleSplit(text, font_name, font_pts, width)

    canv.saveState()
    canv.setFont(font_name, font_pts)
    canv.setFillColor(line_color)

    max_lines = max(1, int(math.floor(height / max(line_spacing, 1.0))))
    truncated = lines[:max_lines]
    y = y_bottom + height - font_pts * 0.85
    for line in truncated:
        canv.drawString(x, y, line)
        y -= line_spacing
        if y <= y_bottom:
            break
    canv.restoreState()


def _build_table(
    data: list[list[str]],
    spans: list[tuple[int, int, int]],
    font_pts: float,
    col_widths: list[float],
    line_color: Color,
) -> Table:
    style = ParagraphStyle(
        "table-cell",
        fontName="Helvetica",
        fontSize=font_pts,
        leading=font_pts * 1.12,
        textColor=line_color,
        alignment=TA_LEFT,
        wordWrap="LTR",
    )

    styled_rows: list[list[Paragraph | str]] = []
    for row in data:
        styled_row: list[Paragraph | str] = []
        for cell in row:
            cell_text = str(cell or "")
            if cell_text.strip():
                escaped = escape(cell_text).replace("\n", "<br />")
            else:
                escaped = "&nbsp;"
            styled_row.append(Paragraph(escaped, style))
        styled_rows.append(styled_row)

    table = Table(styled_rows, colWidths=col_widths, repeatRows=1)
    style_commands = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.45, parse_color("#d1d5db")),
        ("INNERGRID", (0, 0), (-1, -1), 0.65, parse_color("#e5e7eb")),
        ("BOX", (0, 0), (-1, -1), 0.9, parse_color("#94a3b8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for row, start, end in spans:
        style_commands.append(("SPAN", (start, row), (end, row)))
    table.setStyle(TableStyle(style_commands))
    return table


def draw_table(
    canv: canvas.Canvas,
    *,
    x: float,
    y_bottom: float,
    box_width: float,
    box_height: float,
    table_html: str,
    font_pts: float,
    line_color: Color,
) -> None:
    data, spans, column_weights = parse_table_html(table_html)
    if not data:
        return

    columns = len(data[0])
    if columns == 0:
        return

    weight_total = sum(column_weights) or columns
    # minimum width to avoid collapsed columns, but keep proportional balance
    min_width = max(12.0, box_width / columns * 0.15)
    col_widths = [
        max(min_width, box_width * (weight / weight_total)) for weight in column_weights
    ]
    width_sum = sum(col_widths)
    if width_sum > 0:
        normaliser = box_width / width_sum
        col_widths = [width * normaliser for width in col_widths]

    # try to fit the table within the box by gradually shrinking the font
    best_table: Table | None = None
    best_width = box_width
    best_height = box_height
    attempt_font = max(6.5, min(14.0, font_pts))

    for _ in range(12):
        table = _build_table(data, spans, attempt_font, col_widths, line_color)
        table_width, table_height = table.wrap(box_width, box_height)
        if table_width <= box_width + 0.5 and table_height <= box_height + 0.5:
            best_table = table
            best_width = table_width
            best_height = table_height
            break
        best_table = table
        best_width = min(table_width, box_width)
        best_height = min(table_height, box_height)
        attempt_font = max(5.5, attempt_font * 0.9)

    if best_table is None:
        return

    offset_x = x + max(0.0, (box_width - best_width) / 2.0)
    offset_y = y_bottom + max(0.0, box_height - best_height)
    best_table.drawOn(canv, offset_x, offset_y)


def draw_legend(
    canv: canvas.Canvas,
    *,
    margin: float,
    page_height: float,
    page_width: float,
    items: Sequence[tuple[str, str, str]],
) -> None:
    if not items:
        return

    font_size = 9.0
    circle_radius = 3.8
    padding_after = 10.0
    max_width = page_width - 2.0
    max_iterations = 6
    font_name = "Helvetica"

    def measure_widths(size: float, radius: float, pad: float) -> tuple[list[float], float]:
        widths_local: list[float] = []
        total_local = 0.0
        for label, _, _ in items:
            text_width = pdfmetrics.stringWidth(label, font_name, size)
            item_width = (2 * radius) + 6 + text_width + pad
            widths_local.append(item_width)
            total_local += item_width
        return widths_local, total_local

    widths, total = measure_widths(font_size, circle_radius, padding_after)

    while total > max_width and font_size > 6.0 and max_iterations > 0:
        scale = max_width / (total + 1e-6)
        adjust = max(0.65, min(0.92, scale))
        font_size = max(6.0, font_size * adjust)
        circle_radius = max(2.2, circle_radius * adjust)
        padding_after = max(5.0, padding_after * adjust)
        widths, total = measure_widths(font_size, circle_radius, padding_after)
        max_iterations -= 1
        if total <= max_width:
            break

    widths, total = measure_widths(font_size, circle_radius, padding_after)

    line_height = font_size + 9.0
    badge_height = font_size + 6.0
    y_top = margin - 4.0
    rect_y = y_top - badge_height
    if rect_y < 4.0:
        delta = 4.0 - rect_y
        y_top += delta
        rect_y += delta

    canv.saveState()
    canv.setFont(font_name, font_size)

    ascent = pdfmetrics.getAscent(font_name) * font_size / 1000.0
    descent = abs(pdfmetrics.getDescent(font_name)) * font_size / 1000.0
    baseline_offset = (ascent - descent) / 2.0

    x = margin
    for (label, accent_hex, background_hex), item_width in zip(items, widths):
        canv.setFillColor(parse_color(background_hex))
        canv.roundRect(x, rect_y, item_width, badge_height, 5, stroke=0, fill=1)

        canv.setFillColor(parse_color(accent_hex))
        canv.circle(x + circle_radius + 3, rect_y + badge_height / 2.0, circle_radius, stroke=0, fill=1)

        canv.setFillColor(parse_color("#0f172a"))
        center_y = rect_y + badge_height / 2.0
        text_y = center_y - baseline_offset
        canv.drawString(x + (2 * circle_radius) + 8, text_y, label)

        x += item_width

    canv.restoreState()


def draw_image(
    canv: canvas.Canvas,
    *,
    x: float,
    y_bottom: float,
    box_width: float,
    box_height: float,
    image_base64: str,
) -> None:
    data_part = image_base64.strip()
    if not data_part:
        return
    comma_index = data_part.find(",")
    if data_part[:5].lower() == "data:" and comma_index != -1:
        data_part = data_part[comma_index + 1 :]

    try:
        binary = base64.b64decode(data_part, validate=False)
    except (ValueError, binascii.Error):
        return

    if not binary:
        return

    image_stream = BytesIO(binary)
    try:
        img_reader = ImageReader(image_stream)
    except Exception:
        return

    try:
        img_width, img_height = img_reader.getSize()
    except Exception:
        return
    if img_width <= 0 or img_height <= 0:
        return

    scale = max(box_width / img_width, box_height / img_height)
    scaled_width = img_width * scale
    scaled_height = img_height * scale
    offset_x = x + (box_width - scaled_width) / 2.0
    offset_y = y_bottom + (box_height - scaled_height) / 2.0

    canv.saveState()
    clip = canv.beginPath()
    clip.rect(x, y_bottom, box_width, box_height)
    canv.clipPath(clip, stroke=0, fill=0)
    canv.drawImage(
        img_reader,
        offset_x,
        offset_y,
        width=scaled_width,
        height=scaled_height,
        preserveAspectRatio=False,
        mask="auto",
    )
    canv.restoreState()


def _tooltip_text(
    element: Mapping[str, object],
    *,
    page_label: str,
    el_type: str,
    raw_text: str,
    table_html: str | None,
) -> str | None:
    """Compose a tooltip payload summarising the element."""
    parts: list[str] = [f"Page: {page_label}", f"Type: {el_type}"]

    metadata = element.get("metadata") if isinstance(element, Mapping) else None
    element_id = None
    if isinstance(metadata, Mapping):
        element_id = metadata.get("id") or metadata.get("element_id") or metadata.get("filename")
    if element_id:
        parts.append(f"ID: {element_id}")

    summary_source = raw_text.strip()
    if not summary_source and table_html:
        summary_source = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", table_html)).strip()
    if summary_source:
        compact = re.sub(r"\s+", " ", summary_source)
        if len(compact) > 420:
            compact = compact[:417].rstrip() + "..."
        parts.append(f"Text: {compact}")

    tooltip = "\n".join(parts)
    tooltip = tooltip.strip()
    if not tooltip:
        return None
    if len(tooltip) > 600:
        tooltip = tooltip[:597].rstrip() + "..."
    tooltip = tooltip.replace("\x00", " ")
    return tooltip


def _add_mouseover_annotation(
    canv: canvas.Canvas,
    *,
    rect: tuple[float, float, float, float],
    contents: str,
    name: str,
) -> None:
    x1, y1, x2, y2 = rect
    min_size = 8.0
    if x2 - x1 < min_size:
        x2 = x1 + min_size
    if y2 - y1 < min_size:
        y2 = y1 + min_size
    try:
        canv.textAnnotation(
            contents,
            Rect=(x1, y1, x2, y2),
            relative=0,
            name=name,
            Open=0,
        )
    except Exception:
        # Ignore annotation failures to keep PDF generation resilient.
        pass


def _annotation_rect(
    *,
    pdf_x: float,
    pdf_y: float,
    box_width: float,
    box_height: float,
) -> tuple[float, float, float, float] | None:
    if box_width <= 0 or box_height <= 0:
        return None

    padding = max(1.5, min(6.0, box_width * 0.05, box_height * 0.05))
    available_w = box_width - (2 * padding)
    available_h = box_height - (2 * padding)
    size = min(16.0, available_w, available_h)
    if size < 6.0:
        return None
    if size < 8.0:
        size = max(6.0, size)
    else:
        size = max(8.0, min(size, 18.0))
    size = min(size, available_w, available_h)
    if size < 6.0:
        return None

    x2 = pdf_x + box_width - padding
    x1 = x2 - size
    if x1 < pdf_x + padding:
        x1 = pdf_x + padding
        x2 = x1 + size

    y1 = pdf_y + padding
    y2 = y1 + size
    max_y = pdf_y + box_height - padding
    if y2 > max_y:
        y2 = max_y
        y1 = y2 - size
        if y1 < pdf_y + padding:
            y1 = pdf_y + padding
            y2 = y1 + size

    return x1, y1, x2, y2


def render_pdf(
    json_path: Path,
    output_path: Path,
    *,
    title: str,
    elements: Sequence[Mapping[str, object]],
    target_width: float,
    margin: float,
    enable_mouseover: bool,
) -> None:
    grouped = grouped_by_page(elements)
    if not grouped:
        raise SystemExit("No pages detected in JSON input.")

    canv = canvas.Canvas(str(output_path))

    for page_label, page_elements in grouped.items():
        width, height = resolve_page_dimensions(page_elements)
        if width <= 0 or height <= 0:
            width, height = 1000.0, 1414.0

        scale = target_width / width
        page_height = height * scale
        canv.setPageSize((target_width + 2 * margin, page_height + 2 * margin))
        canv.saveState()
        canv.setFillColor(parse_color("#0f172a"))
        canv.setFont("Helvetica-Bold", 13)
        canv.drawString(margin, page_height + margin + 14, f"Page {page_label} – {title}")
        canv.restoreState()

        legend_sequence: list[tuple[str, str, str]] = []
        seen_types: set[str] = set()
        for element in page_elements:
            el_type = element_type(element)
            if el_type not in seen_types:
                seen_types.add(el_type)
                accent_hex, background_hex = color_for_type(el_type)
                legend_sequence.append((el_type, accent_hex, background_hex))

        draw_legend(
            canv,
            margin=margin,
            page_height=page_height,
            page_width=target_width,
            items=legend_sequence,
        )

        canv.saveState()
        canv.setStrokeColor(parse_color("#d0d7de"))
        canv.rect(
            margin,
            margin,
            target_width,
            page_height,
            stroke=1,
            fill=0,
        )
        canv.restoreState()

        for element_index, element in enumerate(page_elements, start=1):
            el_type = element_type(element)
            accent_hex, background_hex = color_for_type(el_type)
            metadata = element.get("metadata") if isinstance(element, Mapping) else None
            box = extract_box(metadata.get("coordinates") if isinstance(metadata, Mapping) else None)
            if not box:
                continue

            left = float(box["left"]) if box.get("left") is not None else 0.0
            top = float(box["top"]) if box.get("top") is not None else 0.0
            box_width = float(box["width"]) if box.get("width") is not None else 0.0
            box_height = float(box["height"]) if box.get("height") is not None else 0.0

            scaled_width = box_width * scale
            scaled_height = box_height * scale
            pdf_x = margin + left * scale
            pdf_y = margin + (height - (top + box_height)) * scale

            canv.saveState()
            canv.setFillColor(parse_color(background_hex))
            canv.setStrokeColor(parse_color(accent_hex))
            canv.roundRect(pdf_x, pdf_y, scaled_width, scaled_height, 12, stroke=1, fill=1)
            canv.restoreState()

            table_html = None
            image_base64 = None
            if isinstance(metadata, Mapping):
                if el_type.lower() == "table":
                    candidate = metadata.get("text_as_html")
                    if isinstance(candidate, str) and candidate.strip():
                        table_html = candidate
                image_candidate = metadata.get("image_base64")
                if isinstance(image_candidate, str) and image_candidate.strip():
                    image_base64 = image_candidate

            raw_text = element_text(element)

            if table_html:
                font_scale = estimate_font_scale(
                    text=re.sub(r"<[^>]+>", "", table_html),
                    box_width=box_width,
                    box_height=box_height,
                    safe_width=width,
                    safe_height=height,
                )
                font_pts = (font_scale or 0.92) * 12.0
                draw_table(
                    canv,
                    x=pdf_x,
                    y_bottom=pdf_y,
                    box_width=scaled_width,
                    box_height=scaled_height,
                    table_html=table_html,
                    font_pts=font_pts,
                    line_color=parse_color("#1f2937"),
                )
            elif image_base64:
                draw_image(
                    canv,
                    x=pdf_x,
                    y_bottom=pdf_y,
                    box_width=scaled_width,
                    box_height=scaled_height,
                    image_base64=image_base64,
                )
            else:
                font_scale = estimate_font_scale(
                    text=raw_text,
                    box_width=box_width,
                    box_height=box_height,
                    safe_width=width,
                    safe_height=height,
                )
                font_pts = (font_scale or 0.92) * 13.5
                draw_wrapped_text(
                    canv,
                    x=pdf_x + 10,
                    y_bottom=pdf_y + 10,
                    width=max(1.0, scaled_width - 20),
                    height=max(1.0, scaled_height - 20),
                    text=raw_text,
                    font_pts=font_pts,
                    line_color=parse_color("#1f2937"),
                )

            if enable_mouseover:
                tooltip = _tooltip_text(
                    element,
                    page_label=str(page_label),
                    el_type=el_type,
                    raw_text=raw_text,
                    table_html=table_html,
                )
                if tooltip:
                    rect = _annotation_rect(
                        pdf_x=pdf_x,
                        pdf_y=pdf_y,
                        box_width=max(1.0, scaled_width),
                        box_height=max(1.0, scaled_height),
                    )
                    if rect:
                        _add_mouseover_annotation(
                            canv,
                            rect=rect,
                            contents=tooltip,
                            name=f"hover-{page_label}-{element_index}",
                        )

        canv.showPage()

    canv.save()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a coordinate-aligned PDF from the JSON produced by the Unstructured pipeline. "
            "The resulting pages preserve layout, tables, and page positions."
        )
    )
    parser.add_argument("json_path", type=Path, help="Path to the layout JSON file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Destination PDF path. Defaults to <json_path>.layout.pdf.",
    )
    parser.add_argument(
        "--target-width",
        type=float,
        default=DEFAULT_PAGE_WIDTH,
        help="Target PDF page width in points (default: width of A4 landscape ~595pt).",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=DEFAULT_MARGIN,
        help="Margin in points surrounding the rendered page (default: 36pt).",
    )
    parser.add_argument(
        "--title",
        type=str,
        help="Optional custom title printed in the PDF header.",
    )
    parser.add_argument(
        "--hover-tooltips",
        action="store_true",
        help="Embed mouse-over tooltips in the PDF with element type and text snippets.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.json_path.exists():
        print(f"JSON file not found: {args.json_path}", file=sys.stderr)
        return 1

    elements = load_elements(args.json_path)
    title = args.title or args.json_path.name
    output_pdf = args.output or args.json_path.with_suffix(".layout.pdf")

    render_pdf(
        args.json_path,
        output_pdf,
        title=title,
        elements=elements,
        target_width=args.target_width,
        margin=args.margin,
        enable_mouseover=args.hover_tooltips,
    )

    print(f"PDF written to {output_pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
