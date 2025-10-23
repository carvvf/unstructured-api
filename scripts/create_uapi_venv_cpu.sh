#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_NAME="${VENV_NAME:-uapi_venv_cpu}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TORCH_VERSION="${TORCH_VERSION:-2.7.1}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.22.1}"
TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-2.7.1}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
ONNXRUNTIME_VERSION="${ONNXRUNTIME_VERSION:-1.22.0}"
PADDLE_VERSION="${PADDLE_VERSION:-2.6.2}"
UNSTRUCTURED_PADDLEOCR_VERSION="${UNSTRUCTURED_PADDLEOCR_VERSION:-2.10.0}"
PYTHON_DOCTR_VERSION="${PYTHON_DOCTR_VERSION:-1.0.0}"

if [[ -d "$ROOT_DIR/$VENV_NAME" ]]; then
    echo "Reusing existing virtual environment at $ROOT_DIR/$VENV_NAME"
else
    "$PYTHON_BIN" -m venv "$ROOT_DIR/$VENV_NAME"
fi

# shellcheck disable=SC1090
source "$ROOT_DIR/$VENV_NAME/bin/activate"

python -m pip install --upgrade pip setuptools wheel

TMP_REQUIREMENTS="$(mktemp)"
trap 'rm -f "$TMP_REQUIREMENTS"' EXIT
cp "$ROOT_DIR/unstructured-api/requirements/base.txt" "$TMP_REQUIREMENTS"

sed -i "s/^torch==${TORCH_VERSION}\$/torch==${TORCH_VERSION}+cpu/" "$TMP_REQUIREMENTS"
sed -i "s/^torchvision==${TORCHVISION_VERSION}\$/torchvision==${TORCHVISION_VERSION}+cpu/" "$TMP_REQUIREMENTS"
sed -i "s/^torchaudio==${TORCHAUDIO_VERSION}\$/torchaudio==${TORCHAUDIO_VERSION}+cpu/" "$TMP_REQUIREMENTS"

pip install -r "$TMP_REQUIREMENTS" \
    --extra-index-url "$TORCH_INDEX_URL"

pip install --upgrade "onnxruntime==${ONNXRUNTIME_VERSION}"

# High-accuracy OCR backends (PaddleOCR + docTR) and their runtimes.
pip install \
    "paddlepaddle==${PADDLE_VERSION}" \
    "unstructured-paddleocr==${UNSTRUCTURED_PADDLEOCR_VERSION}" \
    "python-doctr==${PYTHON_DOCTR_VERSION}"

# Replace yanked packages with supported releases.
pip install --no-deps --upgrade \
    "XlsxWriter==3.2.9" \
    "pypdfium2==4.30.0"

echo "Virtual environment ready at $ROOT_DIR/$VENV_NAME"
