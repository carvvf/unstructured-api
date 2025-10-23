from __future__ import annotations

import os
from typing import TYPE_CHECKING, Iterable

import numpy as np
from PIL import Image as PILImage

from unstructured.documents.elements import ElementType
from unstructured.logger import logger, trace_logger
from unstructured.partition.utils.ocr_models.ocr_interface import OCRAgent
from unstructured.utils import requires_dependencies

if TYPE_CHECKING:
    from unstructured_inference.inference.elements import TextRegions
    from unstructured_inference.inference.layoutelement import LayoutElements


class OCRAgentDocTR(OCRAgent):
    """OCR service implementation using Mindee docTR."""

    def __init__(self, language: str = "en"):
        self.language = self._normalize_language(language)
        self.det_arch = os.environ.get("UNSTRUCTURED_DOCTR_DET_ARCH", "db_resnet50")
        self.reco_arch = os.environ.get("UNSTRUCTURED_DOCTR_RECO_ARCH", "crnn_vgg16_bn")
        self.det_batch = int(os.environ.get("UNSTRUCTURED_DOCTR_DET_BATCH_SIZE", "2"))
        self.reco_batch = int(os.environ.get("UNSTRUCTURED_DOCTR_RECO_BATCH_SIZE", "128"))
        self._device_hint = os.environ.get("UNSTRUCTURED_DOCTR_DEVICE", "auto").lower()
        self._export_as_straight_boxes = (
            os.environ.get("UNSTRUCTURED_DOCTR_EXPORT_STRAIGHT_BOXES", "false").lower() in ("1", "true", "t")
        )
        self.agent = self._load_predictor()

    @requires_dependencies("doctr")
    def _load_predictor(self):
        from doctr.models import ocr_predictor

        predictor = ocr_predictor(
            det_arch=self.det_arch,
            reco_arch=self.reco_arch,
            pretrained=True,
            det_bs=self.det_batch,
            reco_bs=self.reco_batch,
            assume_straight_pages=True,
            export_as_straight_boxes=self._export_as_straight_boxes,
        )

        device = self._resolve_device()
        predictor = predictor.to(device)
        logger.info(
            "Loaded docTR OCR backend with det=%s reco=%s on device=%s", self.det_arch, self.reco_arch, device
        )
        return predictor.eval()

    @requires_dependencies("torch")
    def _resolve_device(self) -> str:
        import torch

        if self._device_hint == "cpu":
            return "cpu"
        if self._device_hint == "gpu":
            if torch.cuda.is_available():
                return "cuda"
            logger.warning("docTR GPU requested but CUDA is unavailable; falling back to CPU.")
            return "cpu"
        # auto
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _normalize_language(self, language: str | None) -> str:
        if not language:
            return "en"
        normalized = language.replace("+", ",").split(",")[0].strip().lower()
        # docTR supports ISO 639-1 codes; map basic english/italian names.
        mapping = {"english": "en", "eng": "en", "italian": "it", "ita": "it"}
        return mapping.get(normalized, normalized or "en")

    def get_text_from_image(self, image: PILImage.Image) -> str:
        ocr_regions = self.get_layout_from_image(image)
        return "\n".join(filter(None, map(str, ocr_regions.texts)))

    def is_text_sorted(self) -> bool:
        # docTR preserves reading order from detection stage.
        return True

    @requires_dependencies("doctr")
    def _run_predictor(self, image: PILImage.Image):
        arr = np.array(image.convert("RGB"))
        trace_logger.detail("Processing entire page OCR with docTR...")
        return self.agent([arr])

    @requires_dependencies("doctr")
    def get_layout_from_image(self, image: PILImage.Image) -> TextRegions:
        from unstructured.partition.pdf_image.inference_utils import build_text_region_from_coords
        from unstructured_inference.inference.elements import TextRegions

        logger.info("docTR OCR processing page with language=%s", self.language)
        doc = self._run_predictor(image)
        page = doc.pages[0]
        height, width = page.dimensions
        text_regions = [
            build_text_region_from_coords(*self._absolute_bbox(line.geometry, width, height), text=line.render().strip())
            for line in self._iter_lines(page.blocks)
            if line.render().strip()
        ]

        if not text_regions:
            return TextRegions.from_list([])
        return TextRegions.from_list(text_regions)

    @requires_dependencies("doctr")
    def get_layout_elements_from_image(self, image: PILImage.Image) -> LayoutElements:
        from unstructured_inference.inference.layoutelement import LayoutElements

        ocr_regions = self.get_layout_from_image(image)
        if len(ocr_regions) == 0:
            return LayoutElements(
                element_coords=np.empty((0, 4)),
                texts=np.array([]),
                element_class_ids=np.zeros((0,), dtype=int),
                element_class_id_map={0: ElementType.UNCATEGORIZED_TEXT},
            )

        return LayoutElements(
            element_coords=ocr_regions.element_coords,
            texts=ocr_regions.texts,
            element_class_ids=np.zeros(ocr_regions.texts.shape, dtype=int),
            element_class_id_map={0: ElementType.UNCATEGORIZED_TEXT},
        )

    @staticmethod
    def _iter_lines(blocks: Iterable):
        for block in blocks:
            for line in getattr(block, "lines", []):
                yield line

    @staticmethod
    def _absolute_bbox(geometry, width: int, height: int) -> tuple[float, float, float, float]:
        coords = np.asarray(geometry, dtype=float)
        if coords.ndim == 1:
            coords = coords.reshape(-1, 2)
        x_vals = coords[:, 0]
        y_vals = coords[:, 1]
        x1 = float(x_vals.min() * width)
        y1 = float(y_vals.min() * height)
        x2 = float(x_vals.max() * width)
        y2 = float(y_vals.max() * height)
        # Clamp to valid image bounds.
        x1 = max(0.0, min(x1, float(width)))
        y1 = max(0.0, min(y1, float(height)))
        x2 = max(x1, min(x2, float(width)))
        y2 = max(y1, min(y2, float(height)))
        return x1, y1, x2, y2
