#!/data/data/com.termux/files/usr/bin/bash
# Measures decode and prefill speed (llama-bench) and samples battery current,
# voltage and temperature at 1 Hz while it runs.
# For POWER numbers the phone must be UNPLUGGED (current_now is then the draw);
# for the "charging" scenario repeat plugged in and report it separately.
set -euo pipefail
OUT=~/phonebench/$(getprop ro.product.model | tr ' ' _)_$(date +%Y%m%d_%H%M%S)
mkdir -p "$OUT"
getprop > "$OUT/getprop.txt"
cat /proc/meminfo > "$OUT/meminfo.txt"
THREADS=${THREADS:-$(nproc)}
( while true; do
    s=$(termux-battery-status)
    echo "$(date +%s.%N) $s" | tr -d '\n'; echo
    sleep 1
  done ) > "$OUT/battery.log" &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT
for b in 1 2 4 8; do
  ~/llama.cpp/build/bin/llama-bench -m ~/models/model.gguf -t "$THREADS" \
     -p 512 -n 128 -b 512 -ub "$b" -o json > "$OUT/bench_ub$b.json" || true
done
# batching cost: time per decode step with 1..8 sequences in flight
~/llama.cpp/build/bin/llama-batched-bench -m ~/models/model.gguf -t "$THREADS" \
   -c 4096 -npp 128 -ntg 64 -npl 1,2,4,8 --output-format jsonl \
   | grep '^{' > "$OUT/batched.jsonl" || true
# sustained run (thermal throttling): 10 minutes of decode
timeout 600 ~/llama.cpp/build/bin/llama-bench -m ~/models/model.gguf -t "$THREADS" \
   -p 0 -n 2048 -r 20 -o json > "$OUT/bench_sustained.json" || true
echo "results in $OUT"
