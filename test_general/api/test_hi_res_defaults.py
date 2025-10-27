import os
import sys
import types

import pytest

try:
    import unstructured_inference  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - test shim
    inference_module = types.ModuleType("unstructured_inference")
    models_module = types.ModuleType("unstructured_inference.models")
    base_module = types.ModuleType("unstructured_inference.models.base")

    class UnknownModelException(Exception):
        pass

    base_module.UnknownModelException = UnknownModelException
    models_module.base = base_module
    inference_module.models = models_module

    sys.modules["unstructured_inference"] = inference_module
    sys.modules["unstructured_inference.models"] = models_module
    sys.modules["unstructured_inference.models.base"] = base_module

from prepline_general.api import general


def test_resolve_hi_res_model_default(monkeypatch):
    monkeypatch.delenv("UNSTRUCTURED_HI_RES_MODEL_NAME", raising=False)
    assert general._resolve_hi_res_model_name(None) == "yolox"


@pytest.mark.parametrize(
    "requested, expected",
    [
        ("detectron2_mask_rcnn", "detectron2_mask_rcnn"),
        ("doctr", "doctr"),
    ],
)
def test_resolve_hi_res_model_name_passthrough(requested: str, expected: str):
    assert general._resolve_hi_res_model_name(requested) == expected


def test_resolve_hi_res_env_override(monkeypatch):
    monkeypatch.setenv("UNSTRUCTURED_HI_RES_MODEL_NAME", "detectron2_mask_rcnn")
    assert general._resolve_hi_res_model_name(None) == "detectron2_mask_rcnn"
