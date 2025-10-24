#!/usr/bin/env bash

set -euo pipefail

FILE_PATH="/home/carlo/AI/"

FILE_NAME="odg019_16_02_23.pdf"
#FILE_NAME="odg064_08_09_23_All_4.pdf"

curl -X POST http://localhost:8000/general/v0/general \
  -H 'unstructured-api-key: sk-fake-api-key' \
  -H 'accept: application/json' \
  -F 'files=@'$FILE_PATH$FILE_NAME';type=application/pdf' \
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
  | jq '.' | tee $FILE_PATH$FILE_NAME.json
