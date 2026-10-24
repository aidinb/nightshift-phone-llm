#!/usr/bin/env python3
"""Turn bench/ measurements into simulator parameters.

    python3 fit_params.py --device DIR [--device DIR ...] [--rpc rpc*.json] \
        [--net net_*.txt] --out params.json

DIR is one output directory of 02_bench_compute.sh (one per phone model).
The result is a JSON file with a "config" object of phonesim.Config overrides
plus a "provenance" object recording where every number came from. Use it
with:  PHONESIM_PARAMS=params.json python3 ../sim/experiments.py

Scaling from the benchmarked model to the simulated 70B model: decode on a
phone is memory-bandwidth bound, so time per layer scales with the bytes of
weights read per layer. Defaults: 8B Q4_K_M = 32 layers of ~0.135 GB;
70B Q4 = 80 layers of ~0.5 GB (ratio ~3.7). Override with --layer-ratio.
Anything not measured keeps the simulator default.
"""
import argparse
import glob
import json
import os
import re
import statistics

NOMINAL_V = 3.85


def load_json_any(path):
    txt = open(path).read().strip()
    if not txt:
        return []
    try:
        d = json.loads(txt)
        return d if isinstance(d, list) else [d]
    except json.JSONDecodeError:  # jsonl
        return [json.loads(l) for l in txt.splitlines() if l.strip().startswith("{")]


def device(dirpath, n_layers_bench, layer_ratio):
    meminfo = open(os.path.join(dirpath, "meminfo.txt")).read()
    ram_gb = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1)) / 1024 ** 2
    gen_ts, pp_ts = [], []
    for f in glob.glob(os.path.join(dirpath, "bench_ub*.json")):
        for r in load_json_any(f):
            if r.get("n_gen", 0) > 0 and r.get("n_prompt", 0) == 0:
                gen_ts.append(r["avg_ts"])
            elif r.get("n_prompt", 0) > 0 and r.get("n_gen", 0) == 0:
                pp_ts.append((r.get("n_ubatch"), r["avg_ts"]))
    sustained = []
    for name in ("bench_sustained.jsonl", "bench_sustained.json"):
        f = os.path.join(dirpath, name)
        if os.path.exists(f):
            sustained += [r["avg_ts"] for r in load_json_any(f) if r.get("n_gen", 0) > 0]
    out = {"dir": dirpath, "ram_gb": round(ram_gb, 1)}
    if gen_ts:
        tg = statistics.median(gen_ts)
        # sustained (thermally throttled) speed is what a night-long job sees
        tg_use = min(tg, statistics.median(sustained)) if sustained else tg
        out["decode_tok_s"] = tg
        out["decode_tok_s_sustained"] = statistics.median(sustained) if sustained else None
        out["ms_per_layer_70b"] = 1000.0 / tg_use / n_layers_bench * layer_ratio
    if pp_ts and gen_ts:
        best_pp = max(t for _, t in pp_ts)
        out["prefill_efficiency"] = best_pp / statistics.median(gen_ts)
    batched = os.path.join(dirpath, "batched.jsonl")
    if os.path.exists(batched):
        steps = {}
        for r in load_json_any(batched):
            if r.get("tg") and r.get("t_tg"):
                steps[int(r["pl"])] = r["t_tg"] / r["tg"]
        if 1 in steps and len(steps) > 1:
            # step(b) = step(1) * (1 + alpha (b-1)); least squares through the origin
            xs = [b - 1 for b in steps if b > 1]
            ys = [steps[b] / steps[1] - 1 for b in steps if b > 1]
            out["batch_alpha"] = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
    blog = os.path.join(dirpath, "battery.log")
    if os.path.exists(blog):
        watts = []
        for line in open(blog):
            try:
                d = json.loads(line.split(" ", 1)[1])
            except (IndexError, ValueError):
                continue
            if d.get("plugged") == "UNPLUGGED" and d.get("current"):
                cur_a = abs(d["current"]) / (1e6 if abs(d["current"]) > 50 else 1.0)
                v = d.get("voltage") or NOMINAL_V
                v = v / 1000 if v > 100 else v
                watts.append(cur_a * v)
        if len(watts) > 30:
            out["power_active_w"] = statistics.median(watts)
    return out


def rpc_check(paths):
    rows = []
    for p in paths:
        for r in load_json_any(p):
            if r.get("n_gen", 0) > 0:
                rows.append({"file": os.path.basename(p), "decode_tok_s": r["avg_ts"],
                             "ms_per_token": 1000 / r["avg_ts"]})
    return rows


def net(paths):
    rtts = []
    for p in paths:
        txt = open(p).read()
        m = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", txt)
        if m:
            rtts.append(float(m.group(1)) / 1000)
    return statistics.median(rtts) if rtts else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", action="append", default=[])
    ap.add_argument("--share", action="append", type=float, default=[],
                    help="pool share of each --device, same order (default equal)")
    ap.add_argument("--rpc", nargs="*", default=[])
    ap.add_argument("--net", nargs="*", default=[])
    ap.add_argument("--bench-layers", type=int, default=32)
    ap.add_argument("--layer-ratio", type=float, default=0.5 / 0.135)
    ap.add_argument("--usable-frac", type=float, default=0.45)
    ap.add_argument("--out", default="params.json")
    a = ap.parse_args()

    devs = [device(d, a.bench_layers, a.layer_ratio) for d in a.device]
    cfg, prov = {}, {"devices": devs}
    timed = [d for d in devs if "ms_per_layer_70b" in d]
    if timed:
        shares = a.share if len(a.share) == len(timed) else [1.0 / len(timed)] * len(timed)
        cfg["phone_classes"] = [[d["ram_gb"], s, a.usable_frac, round(d["ms_per_layer_70b"], 2)]
                                for d, s in zip(timed, shares)]
    for key in ("prefill_efficiency", "batch_alpha", "power_active_w"):
        vals = [d[key] for d in devs if key in d]
        if vals:
            cfg[key] = round(statistics.median(vals), 4)
    rtt = net(a.net)
    if rtt is not None:
        cfg["hop_latency_s"] = round(rtt / 2, 4)  # one-way
        prov["net_rtt_s"] = rtt
    if a.rpc:
        prov["rpc"] = rpc_check(a.rpc)
    json.dump({"config": cfg, "provenance": prov}, open(a.out, "w"), indent=1)
    print(json.dumps(cfg, indent=1))
    print(f"wrote {a.out}; anything not listed keeps the simulator default")


if __name__ == "__main__":
    main()
