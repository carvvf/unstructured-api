from prepline_general.api.postprocessing import (
    _filter_overlapping_duplicate_elements,
    _filter_single_character_text,
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
