#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_NAME="${VENV_NAME:-.uapi-venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/nightly/cu128}"
TORCH_VERSION="${TORCH_VERSION:-2.10.0.dev20251017}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.25.0.dev20251018}"
TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-2.10.0.dev20251018}"
ML_DTYPES_VERSION="${ML_DTYPES_VERSION:-0.5.3}"

if [[ -z "${ONNXRUNTIME_GPU_WHEEL:-}" ]]; then
    shopt -s nullglob
    default_wheels=("$ROOT_DIR"/onnxruntime/build/Linux/Release/dist/onnxruntime_gpu-*.whl)
    shopt -u nullglob
    if (( ${#default_wheels[@]} )); then
        ONNXRUNTIME_GPU_WHEEL="${default_wheels[0]}"
    else
        echo "ERROR: set ONNXRUNTIME_GPU_WHEEL to the GPU wheel built from onnxruntime or run ./build_onnx.sh." >&2
        exit 1
    fi
fi

if [[ ! -f "$ONNXRUNTIME_GPU_WHEEL" ]]; then
    echo "ERROR: wheel not found at $ONNXRUNTIME_GPU_WHEEL" >&2
    exit 1
fi

if [[ -d "$ROOT_DIR/$VENV_NAME" ]]; then
    echo "Reusing existing virtual environment at $ROOT_DIR/$VENV_NAME"
else
    "$PYTHON_BIN" -m venv "$ROOT_DIR/$VENV_NAME"
fi

# shellcheck disable=SC1090
source "$ROOT_DIR/$VENV_NAME/bin/activate"

python -m pip install --upgrade pip setuptools wheel

pip install -r "$ROOT_DIR/unstructured-api/requirements/base.txt"

# Replace yanked packages with supported releases.
pip install --no-deps --upgrade \
    "XlsxWriter==3.2.9" \
    "pypdfium2==4.30.0"

# Replace CPU builds with GPU-enabled packages.
pip uninstall -y torch torchvision torchaudio onnxruntime || true

pip install --pre \
    --index-url "$TORCH_INDEX_URL" \
    "torch==${TORCH_VERSION}+cu128" \
    "torchvision==${TORCHVISION_VERSION}+cu128" \
    "torchaudio==${TORCHAUDIO_VERSION}+cu128"

pip install "$ONNXRUNTIME_GPU_WHEEL"

pip install "ml-dtypes==${ML_DTYPES_VERSION}"

echo "Virtual environment ready at $ROOT_DIR/$VENV_NAME"
