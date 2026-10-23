"""Runs every simulation experiment in the paper and writes results/*.json.
Usage: python3 experiments.py [--quick]      (figures: python3 figures.py)"""
import json
import os
import statistics
import sys
from multiprocessing import Pool

import phonesim as ps

QUICK = "--quick" in sys.argv
SEEDS = [0, 1] if QUICK else [0, 1, 2, 3, 4]
N = 1000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def job(args):
    name, policy, kw = args
    r = ps.run(policy, **kw)
    if name != "timeline":
        r.pop("timeline")
    return name, policy, kw, r


def summarize(rows, keys):
    out = {}
    for k in keys:
        vals = [r[k] for r in rows]
        out[k] = {"mean": statistics.mean(vals),
                  "sd": statistics.pstdev(vals) if len(vals) > 1 else 0.0}
    return out


KEYS = ["tokens_per_s_per_1k_phones", "gb_per_mtoken", "act_gb_per_mtoken",
        "total_gb_per_mtoken", "gb_per_serving_phone", "failures", "useful_stage_frac",
        "oracle_pipe_frac", "token_time_p50_s", "pass_latency_p50_s", "joules_per_token",
        "mean_running_pipes", "consolidations", "standby_swaps", "eligible_frac"]
POLS = ["restart", "replay", "cacheaware", "standby", "lifetime", "consolidate", "wait",
        "sticky", "nightshift_nowait", "nightshift"]
T975 = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57}   # two-sided 95% t quantiles


def paired(rows, base_rows, key):
    """Mean paired difference (same seed = same phone population) with a 95% CI."""
    by = {r["seed"]: r[key] for r in base_rows}
    d = [r[key] - by[r["seed"]] for r in rows if r["seed"] in by]
    if len(d) < 2:
        return {"mean": d[0] if d else 0.0, "ci95": float("nan"), "n": len(d)}
    half = T975.get(len(d), 2.0) * statistics.stdev(d) / len(d) ** 0.5
    return {"mean": statistics.mean(d), "ci95": half, "n": len(d)}


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = []
    # E2: policy comparison
    for pol in POLS:
        for s in SEEDS:
            jobs.append(("policies", pol, dict(n_phones=N, seed=s)))
    # E1: timeline
    for pol in ["replay", "nightshift"]:
        jobs.append(("timeline", pol, dict(n_phones=N, seed=0)))
    # E3: sensitivity
    sweeps = {
        "prefill_efficiency": [2.0, 4.0, 8.0, 16.0, 32.0],
        "day_dur_median_min": [15.0, 35.0, 90.0],
        "night_prob": [0.5, 0.7, 0.85, 1.0],
        "batch_seqs": [16, 32, 48],
        "hop_latency_s": [0.005, 0.030, 0.060, 0.120],
        "n_phones": [500, 1000, 2000, 4000],
        "cache_blocks": [1, 2, 4, 16],
        "sticky_fallback_s": [0.0, 60.0, 120.0, 300.0, 600.0],
    }
    sweep_pols = {"n_phones": ["replay", "cacheaware", "consolidate", "nightshift"],
                  "cache_blocks": ["replay", "cacheaware", "consolidate", "nightshift"],
                  "sticky_fallback_s": ["nightshift"]}
    for param, values in sweeps.items():
        for v in values:
            for pol in sweep_pols.get(param, ["replay", "nightshift"]):
                for s in SEEDS[:3]:
                    kw = dict(n_phones=N, seed=s)
                    kw[param] = v
                    jobs.append((f"sweep:{param}", pol, kw))
    with Pool(os.cpu_count()) as pool:
        results = pool.map(job, jobs, chunksize=1)

    pol_rows, sweep_rows, timelines = {}, {}, {}
    for name, pol, kw, r in results:
        if name == "policies":
            pol_rows.setdefault(pol, []).append(r)
        elif name == "timeline":
            timelines[pol] = r["timeline"]
        else:
            param = name.split(":", 1)[1]
            sweep_rows.setdefault(param, {}).setdefault(str(kw[param]), {}).setdefault(pol, []).append(r)

    pol_out = {}
    for p, rows in pol_rows.items():
        pol_out[p] = summarize(rows, KEYS)
        pol_out[p]["vs_replay"] = {k: paired(rows, pol_rows["replay"], k)
                                   for k in ("tokens_per_s_per_1k_phones", "total_gb_per_mtoken")}
        pol_out[p]["vs_consolidate"] = {k: paired(rows, pol_rows["consolidate"], k)
                                        for k in ("tokens_per_s_per_1k_phones",)}
    json.dump(pol_out, open(os.path.join(OUT, "policies.json"), "w"), indent=1)
    json.dump({param: {v: {p: summarize(rows, KEYS) for p, rows in pols.items()}
                       for v, pols in vals.items()} for param, vals in sweep_rows.items()},
              open(os.path.join(OUT, "sweeps.json"), "w"), indent=1)
    json.dump(timelines, open(os.path.join(OUT, "timeline.json"), "w"))
    json.dump({"seeds": SEEDS, "n_phones": N, "config_defaults": {
        k: v for k, v in vars(ps.Config()).items() if k != "sessions_override"}},
        open(os.path.join(OUT, "meta.json"), "w"), indent=1, default=str)
    for p, rows in pol_rows.items():
        s = summarize(rows, KEYS)
        print(f"{p:12s} tok/s/1k={s['tokens_per_s_per_1k_phones']['mean']:7.1f}"
              f"±{s['tokens_per_s_per_1k_phones']['sd']:4.1f}  GB/Mtok={s['gb_per_mtoken']['mean']:7.1f}"
              f"  fail={s['failures']['mean']:6.0f}  useful={s['useful_stage_frac']['mean']:.2f}"
              f"  J/tok={s['joules_per_token']['mean']:.1f}")


if __name__ == "__main__":
    main()
