#!/data/data/com.termux/files/usr/bin/bash
# Phone-to-phone RTT and throughput on the same Wi-Fi.
# On phone A: iperf3 -s      On phone B: PEER=<ip of A> bash 03_bench_network.sh
set -euo pipefail
: "${PEER:?set PEER to the other phone's IP}"
OUT=~/phonebench/net_$(date +%Y%m%d_%H%M%S); mkdir -p "$OUT"
ping -c 100 -i 0.2 "$PEER" > "$OUT/ping.txt"
iperf3 -c "$PEER" -t 20 -J > "$OUT/iperf_up.json"
iperf3 -c "$PEER" -t 20 -R -J > "$OUT/iperf_down.json"
# activation-sized messages: 16 KB request/response round trips
python3 - "$PEER" > "$OUT/rpc16k.txt" <<'PY'
import socket, sys, time
# requires: on the peer, `python3 echo_server.py`
s = socket.create_connection((sys.argv[1], 5555)); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
msg = b"x" * 16384; ts = []
for _ in range(500):
    t = time.perf_counter(); s.sendall(msg); got = 0
    while got < len(msg): got += len(s.recv(65536))
    ts.append(time.perf_counter() - t)
ts.sort(); print("p50_ms", 1000 * ts[len(ts)//2], "p99_ms", 1000 * ts[int(len(ts)*.99)])
PY
echo "results in $OUT"
