#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"

VENV_DIR=""
for candidate in "$PROJECT_DIR/.uapi-venv" "$WORKSPACE_DIR/.uapi-venv"; do
  if [[ -f "$candidate/bin/activate" ]]; then
    VENV_DIR="$candidate"
    break
  fi
done

if [[ -z "$VENV_DIR" ]]; then
  echo "ERROR: could not find .uapi-venv. Run scripts/create_uapi_venv.sh to provision it." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
# .\.uapi-venv\Scripts\activate         # Windows PowerShell

cd "$PROJECT_DIR"

### Edit and enable this section to run on CUDA GPU
export UNSTRUCTURED_DISABLE_TENSORRT=1
export UNSTRUCTURED_ONNX_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider
export UNSTRUCTURED_FORCE_CUDA_ONLY=1
export CUDA_VISIBLE_DEVICES=0        # indice della dGPU in nvidia-smi
export ORT_CUDA_DEVICE_ID=0          # stesso indice per onnxruntime

python - <<'PY'
from unstructured_inference.models.base import get_model
model = get_model("detectron2_onnx")
print(model.model.get_providers())
PY


### Configure your client to use the same api key
export UNSTRUCTURED_API_KEY=sk-fake-api-key

export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"

uvicorn prepline_general.api.app:app \
  --log-config "$PROJECT_DIR/logger_config.yaml" \
  --host 0.0.0.0 --port 8000 --reload

#deactivate
