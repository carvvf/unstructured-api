#!/usr/bin/env bash

set -euo pipefail

curl -X POST http://localhost:8000/general/v0/general \
  -H 'unstructured-api-key: sk-fake-api-key' \
  -H 'accept: application/json' \
  -F 'files=@/home/carlo/Documenti/AI/data/odg_2023/odg106_06_11_23.pdf;type=application/pdf' \
  -F 'output_format=application/json' \
  -F 'strategy=hi_res' \
  -F 'coordinates=true' \
  -F 'extract_image_block_types[]=Image' \
  -F 'extract_image_block_types[]=Table' \
  -F 'extract_image_block_types[]=Picture' \
  -F 'extract_image_block_types[]=Formula' \
  -F 'extract_image_block_to_payload=true' \
  -F 'languages=ita' \
  -F 'languages=eng' \
  | jq '.'
