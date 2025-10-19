import os

if os.getenv("UNSTRUCTURED_FORCE_CUDA_ONLY", "1").lower() in {"1", "true", "yes"}:
    from onnxruntime.capi import _pybind_state as ort_state

    _orig_get_available = ort_state.get_available_providers

    def _filtered_providers():
        providers = _orig_get_available()
        blocked = {"TensorrtExecutionProvider", "NvTensorRTRTXExecutionProvider"}
        return [p for p in providers if p not in blocked]

    ort_state.get_available_providers = _filtered_providers

