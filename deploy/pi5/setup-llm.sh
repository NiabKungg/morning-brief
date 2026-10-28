#!/usr/bin/env bash
# One-time Pi 5 setup for the brain: build llama.cpp (LFM3 support landed in b11960) natively for the
# Cortex-A76 and download LiquidAI's QAD Q4_0 checkpoint of LFM3-1.7B, verified by SHA-256.
# Run on the Pi 5:  bash ~/mib/app/deploy/pi5/setup-llm.sh   (needs: sudo apt-get install git cmake build-essential)
set -euo pipefail

LLAMA_TAG=b11960
MODEL=LFM3-1.7B-QAD-Q4_0.gguf
MODEL_SHA256=43a7d09a0e9cba91b63eb7052488b9564569bddfd65754d2e426465e572a7452

mkdir -p ~/mib/src ~/mib/models
cd ~/mib/src
if [ ! -d llama.cpp ]; then
  git clone --depth 1 --branch "$LLAMA_TAG" https://github.com/ggml-org/llama.cpp
fi
cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF
cmake --build build -j4 --target llama-server llama-bench

cd ~/mib/models
if ! echo "$MODEL_SHA256  $MODEL" | sha256sum -c --status 2>/dev/null; then
  curl -fL --retry 5 -C - -o "$MODEL" "https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF/resolve/main/$MODEL"
  echo "$MODEL_SHA256  $MODEL" | sha256sum -c
fi
echo "llama-server: ~/mib/src/llama.cpp/build/bin/llama-server  model: ~/mib/models/$MODEL"
