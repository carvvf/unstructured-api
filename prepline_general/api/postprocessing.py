from __future__ import annotations

from typing import Any, Dict, List, Sequence


def _filter_single_character_text(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop elements whose `text` field collapses to a single character or an empty string."""
    filtered_elements: List[Dict[str, Any]] = []
    for element in elements:
        element_type = element.get("type")
        if element_type == "Image":
            filtered_elements.append(element)
            continue
        text = element.get("text")
        if isinstance(text, str) and len(text.strip()) <= 1:
            continue
        filtered_elements.append(element)
    return filtered_elements


def _filter_overlapping_duplicate_elements(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop elements that duplicate text with low-precision coordinates overlapping a precise entry."""
    candidates: List[
        tuple[int, Dict[str, Any], str, int, tuple[float, float, float, float], bool]
    ] = []
    for index, element in enumerate(elements):
        text = element.get("text")
        if not isinstance(text, str):
            continue
        stripped_text = text.strip()
        if not stripped_text:
            continue

        metadata = element.get("metadata")
        if not isinstance(metadata, dict):
            continue

        page_number = metadata.get("page_number")
        page_number_int = _as_int(page_number)
        if page_number_int is None:
            continue

        coordinates = metadata.get("coordinates")
        bbox = _extract_bounding_box(coordinates)
        if bbox is None:
            continue

        truncated = _coordinates_all_integer(coordinates)
        candidates.append((index, element, stripped_text, page_number_int, bbox, truncated))

    if not candidates:
        return elements

    indexes_to_remove: set[int] = set()
    for i in range(len(candidates)):
        idx_a, elem_a, text_a, page_a, bbox_a, truncated_a = candidates[i]
        if idx_a in indexes_to_remove:
            continue
        for j in range(i + 1, len(candidates)):
            idx_b, elem_b, text_b, page_b, bbox_b, truncated_b = candidates[j]
            if idx_b in indexes_to_remove:
                continue

            if text_a != text_b:
                continue
            if page_a != page_b:
                continue

            if not _boxes_significantly_overlap(bbox_a, bbox_b):
                continue

            if truncated_a == truncated_b:
                continue

            idx_to_remove = idx_a if truncated_a else idx_b
            indexes_to_remove.add(idx_to_remove)

    if not indexes_to_remove:
        return elements

    return [element for index, element in enumerate(elements) if index not in indexes_to_remove]


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _extract_bounding_box(coordinates: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(coordinates, dict):
        return None

    points = coordinates.get("points")
    if not isinstance(points, Sequence):
        return None

    xs: List[float] = []
    ys: List[float] = []
    for point in points:
        if not isinstance(point, Sequence) or len(point) < 2:
            continue
        x = _as_float(point[0])
        y = _as_float(point[1])
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)

    if not xs or not ys:
        return None

    return min(xs), min(ys), max(xs), max(ys)


def _coordinates_all_integer(coordinates: Any) -> bool:
    if not isinstance(coordinates, dict):
        return False

    points = coordinates.get("points")
    if not isinstance(points, Sequence):
        return False

    has_coordinate = False
    for point in points:
        if not isinstance(point, Sequence) or len(point) < 2:
            continue

        for value in point[:2]:
            coord = _as_float(value)
            if coord is None:
                return False
            has_coordinate = True
            if not coord.is_integer():
                return False

    return has_coordinate


def _boxes_significantly_overlap(
    box_a: tuple[float, float, float, float],
    box_b: tuple[float, float, float, float],
    threshold: float = 0.9,
) -> bool:
    min_x_a, min_y_a, max_x_a, max_y_a = box_a
    min_x_b, min_y_b, max_x_b, max_y_b = box_b

    width_a = max_x_a - min_x_a
    height_a = max_y_a - min_y_a
    width_b = max_x_b - min_x_b
    height_b = max_y_b - min_y_b

    if width_a <= 0 or height_a <= 0 or width_b <= 0 or height_b <= 0:
        return False

    intersect_width = min(max_x_a, max_x_b) - max(min_x_a, min_x_b)
    intersect_height = min(max_y_a, max_y_b) - max(min_y_a, min_y_b)

    if intersect_width <= 0 or intersect_height <= 0:
        return False

    intersection_area = intersect_width * intersect_height
    smallest_area = min(width_a * height_a, width_b * height_b)
    if smallest_area <= 0:
        return False

    overlap_ratio = intersection_area / smallest_area
    return overlap_ratio >= threshold
