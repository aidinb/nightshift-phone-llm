# Real multi-phone pipeline (llama.cpp RPC)

This measures an actual model split across 2 to 4 phones, to validate the
simulator's latency model (sum of stage times + one network hop per stage).

1. On every phone: `~/llama.cpp/build/bin/ggml-rpc-server -H 0.0.0.0 -p 50052`
2. On a laptop on the same Wi-Fi, with llama.cpp built with `-DGGML_RPC=ON`:

       ./build/bin/llama-bench -m Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \
         --rpc PHONE1:50052,PHONE2:50052 -ngl 99 -p 512 -n 128 -o json > rpc2.json

   Repeat with 1, 2, 3 and 4 phones. llama.cpp assigns layers to the RPC
   devices by their reported memory; record the split it prints.
3. Compare measured decode time per token with the model's prediction:
   `python3 fit_params.py --rpc rpc*.json`.

Note: llama.cpp's RPC backend is single-request and synchronous, so it
measures latency, not the pipelined throughput the simulator models. That is
fine: latency is the part of the model it validates.
