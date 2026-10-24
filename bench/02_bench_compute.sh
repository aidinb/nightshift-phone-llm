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
    # timeout: termux-battery-status hangs forever if Termux:API is not set up;
    # the sysfs fallback works on phones that leave it readable.
    s=$(timeout 5 termux-battery-status 2>/dev/null || \
        for f in capacity temp current_now voltage_now status; do
          printf '%s=%s ' "$f" "$(cat /sys/class/power_supply/battery/$f 2>/dev/null)"; done)
    echo "$(date +%s.%N) $s" | tr -d '\n'; echo
    sleep 1
  done ) > "$OUT/battery.log" &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT
step() { echo "$(date +%H:%M) $*" | tee -a "$OUT/progress.txt"; }
step "started; writing to $OUT (about 45 min). Check any time: bash status.sh"
for b in 1 2 4 8; do
  step "speed test, batch $b of 1 2 4 8"
  ~/llama.cpp/build/bin/llama-bench -m ~/models/model.gguf -t "$THREADS" \
     -p 512 -n 128 -b 512 -ub "$b" -o json > "$OUT/bench_ub$b.json" || true
done
step "batching test"
# batching cost: time per decode step with 1..8 sequences in flight
~/llama.cpp/build/bin/llama-batched-bench -m ~/models/model.gguf -t "$THREADS" \
   -c 4096 -npp 128 -ntg 64 -npl 1,2,4,8 --output-format jsonl \
   | grep '^{' > "$OUT/batched.jsonl" || true
step "10-minute sustained run"
# sustained run (thermal throttling): 10 minutes of decode
timeout 600 ~/llama.cpp/build/bin/llama-bench -m ~/models/model.gguf -t "$THREADS" \
   -p 0 -n 2048 -r 20 -o json > "$OUT/bench_sustained.json" || true
step "DONE. results in $OUT. Next: bash collect.sh"
