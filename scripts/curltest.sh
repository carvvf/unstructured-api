#!/usr/bin/env bash

set -euo pipefail

curl -X POST http://localhost:8000/general/v0/general \
  -H 'unstructured-api-key: sk-fake-api-key' \
  -H 'accept: application/json' \
  -F 'files=@/home/carlo/AI/odg003_10_01_23.pdf;type=application/pdf' \
  -F 'output_format=application/json' \
  -F 'strategy=hi_res' \
  -F 'hi_res_model_name=detectron2_mask_rcnn' \
  -F 'coordinates=true' \
  -F 'extract_image_block_types[]=Image' \
  -F 'extract_image_block_types[]=Table' \
  -F 'extract_image_block_types[]=Picture' \
  -F 'extract_image_block_types[]=Formula' \
  -F 'extract_image_block_to_payload=true' \
  -F 'languages=ita' \
  -F 'languages=eng' \
  | jq '.'
