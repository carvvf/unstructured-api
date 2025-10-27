#!/usr/bin/env bash

set -euo pipefail

#LAYOUT_MODEL="detectron2_mask_rcnn"
LAYOUT_MODEL="yolox"

#FILE_PATH="/home/carlo/AI/"
FILE_PATH="/home/carlo/Documenti/AI/data/odg_2023/"

#FILE_NAME="odg005_11_01_23.pdf"        # Modello valutazione annuale
#FILE_NAME="odg019_16_02_23.pdf"        # Tabella a pag. 3
#FILE_NAME="odg031_21_03_23.pdf"        # Numerose tabelle
#FILE_NAME="odg041_10_05_23.pdf"        # Testo scansionato
#FILE_NAME="odg052_15_06_23_all_2.pdf"  # Brochure con tabella
#FILE_NAME="odg057_09_08_23.pdf"        # Testo verticale a pag. 3 (all'interno di un box del layout)
#FILE_NAME="odg063_05_09_23.pdf"        # Testo verticale a pag. 4
#FILE_NAME="odg064_08_09_23_All_4.pdf"  # Testo misto nativo + scansione
#FILE_NAME="odg085_23_10_23.pdf"        # Testo misto nativo + scansione
FILE_NAME="odg106_06_11_23.pdf"         # Tutte le pagine al contrario + alcune tabelle ruotate

#FILE_PATH="/home/carlo/Documenti/AI/source/ingestion/unstructured-api/sample-docs/"
#FILE_NAME="layout-parser-paper.pdf"

curl -X POST http://localhost:8000/general/v0/general \
  -H 'unstructured-api-key: sk-fake-api-key' \
  -H 'accept: application/json' \
  -F 'files=@'$FILE_PATH$FILE_NAME';type=application/pdf' \
  -F 'output_format=application/json' \
  -F 'strategy=hi_res' \
  -F 'hi_res_model_name='$LAYOUT_MODEL'' \
  -F 'coordinates=true' \
  -F 'extract_image_block_types[]=Image' \
  -F 'extract_image_block_types[]=Table' \
  -F 'extract_image_block_types[]=Picture' \
  -F 'extract_image_block_types[]=Formula' \
  -F 'extract_image_block_to_payload=true' \
  -F 'languages=ita' \
  -F 'languages=eng' \
  | jq '.' | tee $FILE_PATH$FILE_NAME.json

source ../../.uapi_venv_cpu/bin/activate
./json2pdf.py $FILE_PATH$FILE_NAME.json --hover-tooltips
deactivate

