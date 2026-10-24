#!/data/data/com.termux/files/usr/bin/bash
# Run inside Termux (F-Droid build) on each Android phone.
# Installs llama.cpp, iperf3 and termux-api, and downloads the benchmark model.
set -euo pipefail
pkg update -y
pkg install -y git cmake clang make wget iperf3 termux-api python
termux-setup-storage || true
cd ~
[ -d llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_RPC=ON -DLLAMA_CURL=OFF
cmake --build build --config Release -j"${JOBS:-$(nproc)}" --target llama-bench llama-batched-bench llama-cli rpc-server
mkdir -p ~/models && cd ~/models
# Llama 3.1 8B Instruct, 4-bit (about 4.9 GB). Swap for a 3B model on 6 GB phones.
MODEL_URL=${MODEL_URL:-https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf}
[ -f model.gguf ] || wget -O model.gguf "$MODEL_URL"
echo "setup done: $(getprop ro.product.model) $(getprop ro.soc.model)"
