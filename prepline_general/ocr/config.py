from __future__ import annotations

import os
from typing import Optional

from unstructured.logger import logger
from unstructured.partition.utils import constants as unstructured_constants

DOCTR_OCR_AGENT_QNAME = "prepline_general.ocr.doctr_ocr.OCRAgentDocTR"
PADDLE_OCR_AGENT_QNAME = "prepline_general.ocr.paddle_ocr.OCRAgentPaddle"

_BACKEND_ALIASES = {
    "tesseract": unstructured_constants.OCR_AGENT_TESSERACT,
    "paddle": PADDLE_OCR_AGENT_QNAME,
    "doctr": DOCTR_OCR_AGENT_QNAME,
}


def _resolve_backend(alias: str) -> str:
    """Map a short alias to a fully-qualified OCR agent class path."""
    key = alias.strip().lower()
    return _BACKEND_ALIASES.get(key, alias)


def _ensure_whitelist_contains(module_name: str) -> None:
    if module_name in unstructured_constants.OCR_AGENT_MODULES_WHITELIST:
        return
    unstructured_constants.OCR_AGENT_MODULES_WHITELIST.append(module_name)


def configure_ocr_backend_from_env() -> Optional[str]:
    """Configure the OCR backend based on environment variables.

    Returns the resolved fully-qualified OCR agent class path if one is set, otherwise None.
    """
    backend_alias = os.environ.get("UNSTRUCTURED_OCR_BACKEND")
    qname = None

    if backend_alias:
        qname = _resolve_backend(backend_alias)
        os.environ["OCR_AGENT"] = qname
        logger.info("Configured OCR backend from UNSTRUCTURED_OCR_BACKEND=%s", backend_alias)
    else:
        existing = os.environ.get("OCR_AGENT")
        if existing:
            qname = _resolve_backend(existing)
            if qname != existing:
                os.environ["OCR_AGENT"] = qname
            logger.info("Using OCR backend from existing OCR_AGENT=%s", existing)
        else:
            return None

    module_name = qname.rsplit(".", 1)[0]
    _ensure_whitelist_contains(module_name)
    return qname
