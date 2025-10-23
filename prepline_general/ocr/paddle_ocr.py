from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image as PILImage

from unstructured.documents.elements import ElementType
from unstructured.logger import logger, trace_logger
from unstructured.partition.utils.constants import Source
from unstructured.partition.utils.ocr_models.ocr_interface import OCRAgent
from unstructured.utils import requires_dependencies

if TYPE_CHECKING:
    from unstructured_inference.inference.elements import TextRegion, TextRegions
    from unstructured_inference.inference.layoutelement import LayoutElements

LANGUAGE_ALIASES = {
    "english": "en",
    "eng": "en",
    "ita": "latin",
    "italian": "latin",
    "lat": "latin",
    "latin": "latin",
}


class OCRAgentPaddle(OCRAgent):
    """OCR service implementation for PaddleOCR with relaxed language mapping."""

    def __init__(self, language: str = "en"):
        self.language = self._normalize_language(language)
        logger.info("Loading PaddleOCR backend with language=%s", self.language)
        self.agent = self.load_agent(self.language)

    def _normalize_language(self, language: str | None) -> str:
        if not language:
            return "en"
        tokens = [tok for tok in re.split(r"[+,;]", language.lower()) if tok]
        if not tokens:
            return "en"
        if len(tokens) > 1:
            return "latin"
        token = tokens[0]
        return LANGUAGE_ALIASES.get(token, token)

    def load_agent(self, language: str):
        """Loads the PaddleOCR agent as a global variable to ensure that we only load it once."""

        import paddle
        from unstructured_paddleocr import PaddleOCR

        paddle.disable_signal_handler()
        gpu_available = paddle.device.cuda.device_count() > 0
        if gpu_available:
            logger.info("Loading paddle with GPU on language=%s...", language)
        else:
            logger.info("Loading paddle with CPU on language=%s...", language)
        try:
            paddle_ocr = PaddleOCR(
                use_angle_cls=True,
                use_gpu=gpu_available,
                lang=language,
                enable_mkldnn=True,
                show_log=False,
            )
        except AttributeError:
            paddle_ocr = PaddleOCR(
                use_angle_cls=True,
                use_gpu=gpu_available,
                lang=language,
                enable_mkldnn=False,
                show_log=False,
            )
        return paddle_ocr

    def get_text_from_image(self, image: PILImage.Image) -> str:
        ocr_regions = self.get_layout_from_image(image)
        return "\n\n".join(ocr_regions.texts)

    def is_text_sorted(self):
        return False

    def get_layout_from_image(self, image: PILImage.Image) -> TextRegions:
        """Get the OCR regions from image as a list of text regions with paddle."""

        trace_logger.detail("Processing entire page OCR with paddle...")

        ocr_data = self.agent.ocr(np.array(image), cls=True)
        ocr_regions = self.parse_data(ocr_data)

        return ocr_regions

    @requires_dependencies("unstructured_inference")
    def get_layout_elements_from_image(self, image: PILImage.Image) -> LayoutElements:
        from unstructured_inference.inference.layoutelement import LayoutElements

        ocr_regions = self.get_layout_from_image(image)

        return LayoutElements(
            element_coords=ocr_regions.element_coords,
            texts=ocr_regions.texts,
            element_class_ids=np.zeros(ocr_regions.texts.shape, dtype=int),
            element_class_id_map={0: ElementType.UNCATEGORIZED_TEXT},
        )

    @requires_dependencies("unstructured_inference")
    def parse_data(self, ocr_data: list[Any]) -> TextRegions:
        """Parse the OCR result data to extract a list of TextRegion objects from paddle."""

        from unstructured_inference.inference.elements import TextRegions

        from unstructured.partition.pdf_image.inference_utils import build_text_region_from_coords

        text_regions: list[TextRegion] = []
        for idx in range(len(ocr_data)):
            res = ocr_data[idx]
            if not res:
                continue

            for line in res:
                x1 = min([i[0] for i in line[0]])
                y1 = min([i[1] for i in line[0]])
                x2 = max([i[0] for i in line[0]])
                y2 = max([i[1] for i in line[0]])
                text = line[1][0]
                if not text:
                    continue
                cleaned_text = text.strip()
                if cleaned_text:
                    text_region = build_text_region_from_coords(
                        x1, y1, x2, y2, text=cleaned_text, source=Source.OCR_PADDLE
                    )
                    text_regions.append(text_region)

        return TextRegions.from_list(text_regions)
