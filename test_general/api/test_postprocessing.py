import io
from unittest.mock import Mock

from PIL import Image

from prepline_general.api import postprocessing
from prepline_general.api.postprocessing import (
    _filter_overlapping_duplicate_elements,
    _filter_single_character_text,
    _looks_like_spaced_text,
    _select_primary_language,
    repair_rotated_text_blocks,
)


def test_filter_overlapping_duplicate_elements_removes_truncated_duplicate():
    elements = [
        {
            "type": "Title",
            "element_id": "title-1",
            "text": "Quadro normativo",
            "metadata": {
                "page_number": 4,
                "coordinates": {
                    "system": "PixelSpace",
                    "layout_width": 1654,
                    "layout_height": 2339,
                    "points": [
                        [354.0, 1274.0],
                        [354.0, 1311.0],
                        [588.0, 1311.0],
                        [588.0, 1274.0],
                    ],
                },
            },
        },
        {
            "type": "NarrativeText",
            "element_id": "narrative-1",
            "text": "Quadro normativo",
            "metadata": {
                "page_number": 4,
                "coordinates": {
                    "system": "PixelSpace",
                    "layout_width": 1654,
                    "layout_height": 2339,
                    "points": [
                        [357.3906, 1276.4597],
                        [357.3906, 1309.7931],
                        [594.1397, 1309.7931],
                        [594.1397, 1276.4597],
                    ],
                },
            },
        },
        {
            "type": "NarrativeText",
            "element_id": "narrative-2",
            "text": "Altro testo",
            "metadata": {
                "page_number": 4,
                "coordinates": {
                    "system": "PixelSpace",
                    "layout_width": 1654,
                    "layout_height": 2339,
                    "points": [
                        [100.0, 100.0],
                        [100.0, 150.0],
                        [200.0, 150.0],
                        [200.0, 100.0],
                    ],
                },
            },
        },
    ]

    filtered = _filter_overlapping_duplicate_elements(elements)

    assert [element["element_id"] for element in filtered] == ["narrative-1", "narrative-2"]


def test_filter_overlapping_duplicate_elements_keeps_non_overlapping_entries():
    elements = [
        {
            "type": "Title",
            "element_id": "title-1",
            "text": "Quadro normativo",
            "metadata": {
                "page_number": 4,
                "coordinates": {
                    "system": "PixelSpace",
                    "layout_width": 1654,
                    "layout_height": 2339,
                    "points": [
                        [354.0, 1274.0],
                        [354.0, 1311.0],
                        [588.0, 1311.0],
                        [588.0, 1274.0],
                    ],
                },
            },
        },
        {
            "type": "NarrativeText",
            "element_id": "narrative-1",
            "text": "Quadro normativo",
            "metadata": {
                "page_number": 5,
                "coordinates": {
                    "system": "PixelSpace",
                    "layout_width": 1654,
                    "layout_height": 2339,
                    "points": [
                        [357.3906, 1276.4597],
                        [357.3906, 1309.7931],
                        [594.1397, 1309.7931],
                        [594.1397, 1276.4597],
                    ],
                },
            },
        },
    ]

    filtered = _filter_overlapping_duplicate_elements(elements)

    assert filtered == elements


def test_filter_overlapping_duplicate_elements_handles_same_type_duplicates():
    elements = [
        {
            "type": "Title",
            "element_id": "title-1",
            "text": "Duplicato",
            "metadata": {
                "page_number": 1,
                "coordinates": {
                    "system": "PixelSpace",
                    "layout_width": 800,
                    "layout_height": 1200,
                    "points": [
                        [100.0, 200.0],
                        [100.0, 240.0],
                        [260.0, 240.0],
                        [260.0, 200.0],
                    ],
                },
            },
        },
        {
            "type": "Title",
            "element_id": "title-2",
            "text": "Duplicato",
            "metadata": {
                "page_number": 1,
                "coordinates": {
                    "system": "PixelSpace",
                    "layout_width": 800,
                    "layout_height": 1200,
                    "points": [
                        [102.345, 201.789],
                        [102.345, 238.456],
                        [260.678, 238.456],
                        [260.678, 201.789],
                    ],
                },
            },
        },
    ]

    filtered = _filter_overlapping_duplicate_elements(elements)

    assert [element["element_id"] for element in filtered] == ["title-2"]


def test_filter_single_character_keeps_images():
    elements = [
        {
            "type": "Image",
            "element_id": "img-1",
            "text": "",
            "metadata": {},
        },
        {
            "type": "Image",
            "element_id": "img-2",
            "text": " ",
            "metadata": {},
        },
        {
            "type": "Title",
            "element_id": "title-1",
            "text": " ",
            "metadata": {},
        },
    ]

    filtered = _filter_single_character_text(elements)

    assert [element["element_id"] for element in filtered] == ["img-1", "img-2"]


def test_looks_like_spaced_text_detects_sample():
    spaced_text = (
        "6  3  :  5  1  .  h  O  .  2  R  2  T  S  0  2  I  G  -  E  5  0  R  .  -  1"
        "  N  E  1  G  .  7  F  F  6  4  A  C  6  0  D  .  0  0  f  v  .  U  v  p  .  E"
        "  i  d  L  A  I  C  I  F  F  U "
    )
    assert _looks_like_spaced_text(spaced_text)


def test_looks_like_spaced_text_rejects_normal_text():
    assert not _looks_like_spaced_text("Testo normale senza spazi extra")


def test_repair_rotated_text_blocks_replaces_text_when_candidate_better(monkeypatch):
    spaced_text = (
        "6  3  :  5  1  .  h  O  .  2  R  2  T  S  0  2  I  G  -  E  5  0  R  .  -  1"
        "  N  E  1  G  .  7  F  F  6  4  A  C  6  0  D  .  0  0  f  v  .  U  v  p  .  E"
        "  i  d  L  A  I  C  I  F  F  U "
    )
    elements = [
        {
            "type": "NarrativeText",
            "text": spaced_text,
            "metadata": {
                "page_number": 1,
                "coordinates": {
                    "layout_width": 100,
                    "layout_height": 100,
                    "points": [
                        [0, 0],
                        [0, 100],
                        [100, 100],
                        [100, 0],
                    ],
                },
            },
        }
    ]

    class DummyFetcher:
        def __init__(self, *args, **kwargs):
            self.image = Image.new("RGB", (100, 100), "white")

        def get(self, page_number):
            return self.image

    monkeypatch.setattr(postprocessing, "_PageImageFetcher", DummyFetcher)
    monkeypatch.setattr(
        postprocessing,
        "_rerun_rotated_ocr",
        lambda agent, image, baseline: ("Test ruotato coerente", 90),
    )

    ocr_agent = Mock()
    file_obj = io.BytesIO(b"dummy")

    updated = repair_rotated_text_blocks(elements, file_obj, "application/pdf", ocr_agent, "eng")

    assert updated[0]["text"] == "Test ruotato coerente"
    assert updated[0]["metadata"]["rotated_ocr_fix_applied"] is True
    assert updated[0]["metadata"]["rotated_ocr_angle"] == 90


def test_repair_rotated_text_blocks_skips_when_no_spaced_text(monkeypatch):
    elements = [
        {
            "type": "NarrativeText",
            "text": "Testo normale senza problemi",
            "metadata": {"page_number": 1},
        }
    ]

    def fail(*args, **kwargs):
        raise AssertionError("OCR should not run for non-spaced text")

    monkeypatch.setattr(postprocessing, "_rerun_rotated_ocr", fail)

    result = repair_rotated_text_blocks(
        elements, io.BytesIO(b"dummy"), "application/pdf", Mock(), "eng"
    )
    assert result == elements


def test_coerce_ocr_agent_from_string(monkeypatch):
    mock_agent = Mock()

    def mock_get_instance(*, ocr_agent_module, language):
        assert ocr_agent_module == "path.to.Agent"
        assert language == "ita"
        return mock_agent

    monkeypatch.setattr(
        "unstructured.partition.utils.ocr_models.ocr_interface.OCRAgent.get_instance",
        lambda ocr_agent_module, language: mock_get_instance(
            ocr_agent_module=ocr_agent_module, language=language
        ),
        raising=False,
    )

    agent = postprocessing._coerce_ocr_agent("path.to.Agent", "ita+eng")
    assert agent is mock_agent


def test_select_primary_language_handles_empty():
    assert _select_primary_language(None) == "eng"
    assert _select_primary_language("") == "eng"
    assert _select_primary_language("  ") == "eng"
    assert _select_primary_language("fra+eng") == "fra"
