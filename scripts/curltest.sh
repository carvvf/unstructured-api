#!/usr/bin/env bash

set -euo pipefail

curl -X POST http://localhost:8000/general/v0/general \
  -H 'unstructured-api-key: sk-fake-api-key' \
  -H 'accept: application/json' \
  -F 'files=@../sample-docs/layout-parser-paper.pdf;type=application/pdf' \
  -F 'output_format=application/json' \
  -F 'strategy=hi_res' \
  -F 'hi_res_model_name=yolox' \
  -F 'coordinates=true' \
  | jq '.'
