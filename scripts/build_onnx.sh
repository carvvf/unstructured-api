#!/bin/bash

### As of today, latest NVIDIA cards such as 5070 Ti 12Gb are not yet supported by the main/stable release of onnxruntime
### This script is intended to compile a custom onnxruntime that supports such cards

sudo apt update
sudo apt install -y python3-dev python3-pip python3-numpy build-essential ninja-build git \
    libcudnn9-cuda-12 libcudnn9-dev-cuda-12 libcudnn9-headers-cuda-12

echo ""
echo "###############################################"
echo "Check your C++ compiler version:"
echo "###############################################"
gcc -v

echo ""
echo "###############################################"
echo "Check your NVIDIA compiler version:"
echo "If you need to install NVIDIA drivers and compiler, please refer to NVIDIA official documentation"
echo "###############################################"
nvcc -V

echo ""
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd $ROOT_DIR

git clone https://github.com/microsoft/onnxruntime.git
cd onnxruntime
./build.sh --config Release --build_wheel --build_shared_lib --parallel \
  --use_cuda \
  --cuda_home=/usr/local/cuda-12.8 \
  --cudnn_home=/usr/local/cuda-12.8 \
  --cuda_version=12.8 \
  --cmake_generator Ninja \
  --cmake_extra_defines CMAKE_CUDA_ARCHITECTURES="75;80;86;90;120" \
  --skip_tests

