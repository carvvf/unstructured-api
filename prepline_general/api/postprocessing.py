from __future__ import annotations

import io
import logging
import math
import re
from contextlib import suppress
from typing import IO, TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image as PILImage

logger = logging.getLogger("unstructured_api")

if TYPE_CHECKING:
    from unstructured.partition.utils.ocr_models.ocr_interface import OCRAgent


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


_MIN_TOKENS_FOR_SPACED_TEXT = 8
_MIN_ALPHANUMERIC_TOKENS = 4
_SPACED_TOKEN_RATIO_THRESHOLD = 0.75
_ROTATION_SEQUENCE: Tuple[int, ...] = (90, 270, 180)
_MIN_SCORE_IMPROVEMENT = 0.4


def repair_rotated_text_blocks(
    elements: List[Dict[str, Any]],
    file_obj: IO[bytes],
    content_type: Optional[str],
    ocr_agent: Optional[Any],
    ocr_languages: Optional[str],
) -> List[Dict[str, Any]]:
    """Retain elements but replace text when OCR indicates rotated spaced-out extraction."""
    if not elements or ocr_agent is None:
        return elements

    agent = _coerce_ocr_agent(ocr_agent, ocr_languages)
    if agent is None:
        return elements

    candidate_indexes: List[int] = []
    for idx, element in enumerate(elements):
        text = element.get("text")
        if not isinstance(text, str) or not _looks_like_spaced_text(text):
            continue
        metadata = element.get("metadata")
        if not isinstance(metadata, dict):
            continue
        coordinates = metadata.get("coordinates")
        if not isinstance(coordinates, dict):
            continue
        bbox = _extract_bounding_box(coordinates)
        if bbox is None:
            continue
        page_number = _as_int(metadata.get("page_number"))
        if page_number is None:
            continue
        candidate_indexes.append(idx)

    if not candidate_indexes:
        return elements

    source_bytes = _read_all_bytes(file_obj)
    if not source_bytes:
        logger.debug("Unable to re-read source file for rotated OCR fix; skipping.")
        return elements

    fetcher = _PageImageFetcher(source_bytes, content_type or "")

    for idx in candidate_indexes:
        element = elements[idx]
        metadata = element.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            element["metadata"] = metadata
        page_number = _as_int(metadata.get("page_number"))
        coordinates = metadata.get("coordinates")
        if page_number is None or not isinstance(coordinates, dict):
            continue

        page_image = fetcher.get(page_number)
        if page_image is None:
            continue

        cropped = _crop_image_from_coordinates(page_image, coordinates)
        if cropped is None:
            continue

        original_text = element.get("text", "")
        new_text, applied_angle = _rerun_rotated_ocr(agent, cropped, original_text)
        if not new_text or applied_angle is None:
            continue

        baseline_score = _text_quality_score(original_text)
        candidate_score = _text_quality_score(new_text)

        element["text"] = new_text
        metadata["rotated_ocr_fix_applied"] = True
        metadata["rotated_ocr_angle"] = applied_angle
        metadata["rotated_ocr_baseline_score"] = round(baseline_score, 4)
        metadata["rotated_ocr_candidate_score"] = round(candidate_score, 4)

    return elements


def _looks_like_spaced_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 6:
        return False
    if "  " not in text:
        return False
    tokens = [token for token in stripped.split() if token]
    if len(tokens) < _MIN_TOKENS_FOR_SPACED_TEXT:
        return False
    alnum_tokens = sum(1 for token in tokens if re.search(r"[0-9A-Za-z]", token))
    if alnum_tokens < _MIN_ALPHANUMERIC_TOKENS:
        return False
    single_char_tokens = sum(1 for token in tokens if len(token) == 1)
    if not tokens or (single_char_tokens / len(tokens)) < _SPACED_TOKEN_RATIO_THRESHOLD:
        return False
    return True


def _text_quality_score(text: str) -> float:
    if not isinstance(text, str):
        return 0.0
    stripped = text.strip()
    if not stripped:
        return 0.0
    tokens = [token for token in stripped.split() if token]
    if not tokens:
        return 0.0

    cleaned_lengths: List[int] = []
    alnum_tokens = 0
    for token in tokens:
        cleaned = re.sub(r"^\W+|\W+$", "", token)
        if not cleaned:
            continue
        cleaned_lengths.append(len(cleaned))
        if re.search(r"[0-9A-Za-z]", cleaned):
            alnum_tokens += 1

    if not cleaned_lengths:
        return 0.0

    avg_len = sum(cleaned_lengths) / len(cleaned_lengths)
    single_char_ratio = sum(1 for length in cleaned_lengths if length <= 1) / len(cleaned_lengths)
    alnum_ratio = alnum_tokens / len(tokens)

    score = avg_len * (1 - single_char_ratio)
    score *= max(0.5, alnum_ratio)
    return score


def _read_all_bytes(file_obj: IO[bytes]) -> Optional[bytes]:
    if file_obj is None or not hasattr(file_obj, "read"):
        return None

    try:
        current_pos = file_obj.tell()
    except (AttributeError, OSError):
        current_pos = None

    try:
        with suppress(AttributeError, OSError):
            file_obj.seek(0)
        data = file_obj.read()
        if isinstance(data, bytearray):
            data = bytes(data)
        return data if isinstance(data, (bytes, bytearray)) and data else None
    finally:
        if current_pos is not None:
            with suppress(AttributeError, OSError):
                file_obj.seek(current_pos)


class _PageImageFetcher:
    """Lazily render page images from the source document."""

    def __init__(self, file_bytes: bytes, content_type: str):
        self._file_bytes = file_bytes
        self._content_type = content_type.lower()
        self._pdf_cache: Dict[int, Optional[PILImage.Image]] = {}
        self._image_cache: Optional[Optional[PILImage.Image]] = None

    def get(self, page_number: int) -> Optional[PILImage.Image]:
        if self._content_type == "application/pdf":
            if page_number in self._pdf_cache:
                return self._pdf_cache[page_number]

            try:
                from pdf2image import convert_from_bytes
            except ImportError:
                logger.warning(
                    "pdf2image not installed; skipping rotated OCR fix for page %s", page_number
                )
                self._pdf_cache[page_number] = None
                return None
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Unable to import pdf2image for rotated OCR fix: %s", exc
                )
                self._pdf_cache[page_number] = None
                return None

            try:
                images = convert_from_bytes(
                    self._file_bytes, first_page=page_number, last_page=page_number
                )
            except Exception as exc:
                logger.warning(
                    "Unable to render PDF page %s for rotated OCR fix: %s", page_number, exc
                )
                self._pdf_cache[page_number] = None
                return None

            image = images[0] if images else None
            self._pdf_cache[page_number] = image
            return image

        if self._content_type.startswith("image/"):
            if self._image_cache is not None:
                return self._image_cache
            try:
                image = PILImage.open(io.BytesIO(self._file_bytes))
                self._image_cache = image
                return image
            except Exception as exc:
                logger.warning("Unable to open image for rotated OCR fix: %s", exc)
                self._image_cache = None
                return None

        return None


def _crop_image_from_coordinates(
    page_image: PILImage.Image,
    coordinates: Dict[str, Any],
) -> Optional[PILImage.Image]:
    bbox = _extract_bounding_box(coordinates)
    if bbox is None:
        return None

    layout_width = _as_float(coordinates.get("layout_width"))
    layout_height = _as_float(coordinates.get("layout_height"))

    if layout_width in (None, 0) or layout_height in (None, 0):
        layout_width = float(page_image.width)
        layout_height = float(page_image.height)

    min_x, min_y, max_x, max_y = bbox
    if max_x <= min_x or max_y <= min_y:
        return None

    scale_x = page_image.width / layout_width if layout_width else 1.0
    scale_y = page_image.height / layout_height if layout_height else 1.0

    left = max(0, min(page_image.width - 1, int(math.floor(min_x * scale_x))))
    upper = max(0, min(page_image.height - 1, int(math.floor(min_y * scale_y))))
    right = max(left + 1, min(page_image.width, int(math.ceil(max_x * scale_x))))
    lower = max(upper + 1, min(page_image.height, int(math.ceil(max_y * scale_y))))

    if right - left < 2 or lower - upper < 2:
        return None

    return page_image.crop((left, upper, right, lower))


def _rerun_rotated_ocr(
    ocr_agent: "OCRAgent", image: PILImage.Image, baseline_text: str
) -> Tuple[Optional[str], Optional[int]]:
    baseline_score = _text_quality_score(baseline_text)
    best_text: Optional[str] = None
    best_angle: Optional[int] = None
    best_score = baseline_score

    for angle in _ROTATION_SEQUENCE:
        rotated = image.rotate(angle, expand=True)
        try:
            candidate_text = ocr_agent.get_text_from_image(rotated)
        except Exception as exc:  # pragma: no cover
            logger.debug("Rotated OCR attempt failed at angle %s: %s", angle, exc)
            continue

        candidate_text = (candidate_text or "").strip()
        if not candidate_text:
            continue

        candidate_score = _text_quality_score(candidate_text)
        if candidate_score >= best_score + _MIN_SCORE_IMPROVEMENT:
            best_text = candidate_text
            best_score = candidate_score
            best_angle = angle

    return best_text, best_angle


def _coerce_ocr_agent(ocr_agent: Any, ocr_languages: Optional[str]) -> Optional["OCRAgent"]:
    if ocr_agent is None:
        return None

    if hasattr(ocr_agent, "get_text_from_image"):
        return ocr_agent

    if isinstance(ocr_agent, str):
        try:
            from unstructured.partition.utils.ocr_models.ocr_interface import OCRAgent as _OCRAgent
        except Exception as exc:  # pragma: no cover
            logger.warning("Unable to import OCRAgent interface: %s", exc)
            return None

        language = _select_primary_language(ocr_languages)
        try:
            return _OCRAgent.get_instance(ocr_agent_module=ocr_agent, language=language)
        except Exception as exc:  # pragma: no cover
            logger.warning("Unable to instantiate OCR agent %s: %s", ocr_agent, exc)
            return None

    logger.debug("Unsupported OCR agent type for rotated OCR fix: %s", type(ocr_agent))
    return None


def _select_primary_language(ocr_languages: Optional[str]) -> str:
    if not isinstance(ocr_languages, str) or not ocr_languages.strip():
        return "eng"
    return ocr_languages.split("+")[0].strip() or "eng"
