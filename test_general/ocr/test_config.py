import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from prepline_general.ocr import config


def test_configure_defaults_to_paddle(monkeypatch):
    monkeypatch.delenv("UNSTRUCTURED_OCR_BACKEND", raising=False)
    monkeypatch.delenv("OCR_AGENT", raising=False)

    original_whitelist = list(config.unstructured_constants.OCR_AGENT_MODULES_WHITELIST)
    monkeypatch.setattr(
        config.unstructured_constants,
        "OCR_AGENT_MODULES_WHITELIST",
        original_whitelist.copy(),
        raising=False,
    )

    result = config.configure_ocr_backend_from_env()

    assert result == config.PADDLE_OCR_AGENT_QNAME
    assert os.environ["OCR_AGENT"] == config.PADDLE_OCR_AGENT_QNAME
    module_name = config.PADDLE_OCR_AGENT_QNAME.rsplit(".", 1)[0]
    assert module_name in config.unstructured_constants.OCR_AGENT_MODULES_WHITELIST


def test_configure_respects_backend_alias(monkeypatch):
    monkeypatch.setenv("UNSTRUCTURED_OCR_BACKEND", "doctr")
    monkeypatch.delenv("OCR_AGENT", raising=False)

    original_whitelist = list(config.unstructured_constants.OCR_AGENT_MODULES_WHITELIST)
    monkeypatch.setattr(
        config.unstructured_constants,
        "OCR_AGENT_MODULES_WHITELIST",
        original_whitelist.copy(),
        raising=False,
    )

    result = config.configure_ocr_backend_from_env()

    assert result == config.DOCTR_OCR_AGENT_QNAME
    assert os.environ["OCR_AGENT"] == config.DOCTR_OCR_AGENT_QNAME
    module_name = config.DOCTR_OCR_AGENT_QNAME.rsplit(".", 1)[0]
    assert module_name in config.unstructured_constants.OCR_AGENT_MODULES_WHITELIST
