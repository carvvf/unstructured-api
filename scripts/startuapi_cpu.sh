#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"

VENV_DIR=""
for candidate in "$PROJECT_DIR/uapi_venv_cpu" "$WORKSPACE_DIR/uapi_venv_cpu"; do
  if [[ -f "$candidate/bin/activate" ]]; then
    VENV_DIR="$candidate"
    break
  fi
done

if [[ -z "$VENV_DIR" ]]; then
  echo "ERROR: could not find uapi_venv_cpu. Run scripts/create_uapi_venv_cpu.sh to provision it." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

cd "$PROJECT_DIR"

export UNSTRUCTURED_ONNX_PROVIDERS=CPUExecutionProvider

python - <<'PY'
from unstructured_inference.models.base import get_model
model = get_model("detectron2_onnx")
print(model.model.get_providers())
PY

export UNSTRUCTURED_LOG_LEVEL=TRACE
export UNSTRUCTURED_TRACE_LOGS=true

export UNSTRUCTURED_API_KEY=sk-fake-api-key
#export UNSTRUCTURED_OCR_BACKEND=paddle
export UNSTRUCTURED_OCR_BACKEND=doctr

python - <<'PY'
from prepline_general.ocr.config import configure_ocr_backend_from_env
print(configure_ocr_backend_from_env())
PY

export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"

uvicorn prepline_general.api.app:app \
  --log-config "$PROJECT_DIR/logger_config.yaml" \
  --host 0.0.0.0 --port 8000 --reload
