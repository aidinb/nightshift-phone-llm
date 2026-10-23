"""Analytical shard-traffic model, checked against the simulator.

The model predicts how many 2.5 GB block downloads each scheduler decision
causes, from one assumption: every idle phone caches one block, uniform over
the B blocks and independent of the others (each phone keeps only the block it
served last, cache_blocks = 1). Under that assumption:

  repair from an idle pool of I phones, matching over the whole pool
      P(download) = q^I,                q = 1 - 1/B
  repair that only looks at the top quarter of the pool (lifetime ranking)
      P(download) = q^max(1, floor(I/4))
  repair under the sticky rule (wait up to W for a home-block phone; phones
  join the idle pool at a rate of a per second)
      P(download) = q^I0 * exp(-a(h) W / B), a(h) at that hour, W = wait left
  pipeline formed from a random group (replay family): a mean-field recursion
      over the greedy take-for-block order (see form_group_misses)
  pipeline formation that matches over the whole pool (cache-aware), n pipes
      from I phones:  E[downloads] = sum_b E[max(0, n - X_b)],  X_b ~ Bin(I, 1/B)
  sticky formation and home-block repair: a download only when the phone has
      drifted (its last block was not its home block, after serving as a
      fallback); the drifted fraction d comes from a balance of fallbacks
      (which create drift) and home uses (which remove it), see predict()

The model takes, as input, the pool sizes the scheduler saw (I, I0), the number of
formations and the session-arrival rate a(h) by hour of day. It does not see which blocks
the phones hold. Traffic per million tokens is then downloads * block_gb / tokens.

Usage: python3 traffic_model.py [--quick]   -> results/traffic_model.json
"""
import json
import math
import os
import statistics
import sys
from multiprocessing import Pool

import phonesim as ps

QUICK = "--quick" in sys.argv
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
POLS = ["restart", "replay", "cacheaware", "standby", "lifetime", "consolidate",
        "wait", "sticky", "nightshift_nowait", "nightshift"]
SCALE_POLS = ["replay", "cacheaware", "consolidate", "nightshift"]


def binom_pmf(n: int, p: float):
    out, c = [], (1 - p) ** n
    for k in range(n + 1):
        out.append(c)
        if k < n:
            c = c * (n - k) / (k + 1) * p / (1 - p)
    return out


def p_some_block_absent(I: int, B: int) -> float:
    """P(at least one of B blocks has no phone among I uniform phones),
    by inclusion-exclusion."""
    return min(1.0, max(0.0, sum((-1) ** (j + 1) * math.comb(B, j) * (1 - j / B) ** I
                                 for j in range(1, B + 1))))


def form_cache_misses(I: int, n: int, B: int) -> float:
    pmf = binom_pmf(I, 1.0 / B)
    per_block = sum(pk * max(0, n - k) for k, pk in enumerate(pmf))
    return B * per_block


def form_group_misses(B: int, k: int, window_quarter: bool) -> float:
    """Expected downloads when one pipeline is formed from a random group of
    B(1+k) phones, taking blocks in the simulator's order (stages 0..B-1, then
    k standbys per block). Mean field: m[c] = expected number of remaining
    phones that cache block c. A take for block b hits if one of the phones it
    may look at caches b (it then removes one such phone); otherwise it removes
    a random phone (the scheduler's fallback, which downloads)."""
    r = B * (1 + k)
    m = [r / B] * B
    order = list(range(B)) + [b for b in range(B) for _ in range(k)]
    misses = 0.0
    for b in order:
        w = max(1, r // 4) if window_quarter else r
        frac = min(1.0, m[b] / r)
        hit = 1 - (1 - frac) ** w
        misses += 1 - hit
        # hit: one phone caching b leaves; miss: a random phone leaves
        for c in range(B):
            m[c] -= (1 - hit) * m[c] / r
        m[b] -= hit
        m[b] = max(0.0, m[b])
        r -= 1
    return misses


def predict(r: dict, policy: str) -> dict:
    cfg = ps.Config(**{**ps.POLICIES[policy]})
    B, q = r["n_blocks"], 1 - 1 / r["n_blocks"]
    quarter = cfg.placement == "lifetime"
    a_h = r["arrivals_per_s_by_hour"]
    sim = {"form": 0, "repair": 0, "refill": 0}
    mod = {"form": 0.0, "repair": 0.0, "refill": 0.0}
    k = cfg.standbys
    per_pipe = B * (1 + k)
    seen_calls = set()
    fallbacks = home_uses = 0.0
    sim_form_events = 0
    for e in r["events"]:
        kind, missed = e[0], e[-1]
        if kind == "form_group":
            sim["form"] += missed
            if e[1] == per_pipe:              # first take of a new formation
                mod["form"] += form_group_misses(B, k, quarter)
        elif kind == "form_cache":
            sim["form"] += missed
            if e[3] not in seen_calls:
                seen_calls.add(e[3])
                mod["form"] += form_cache_misses(e[1], e[2], B)
        elif kind == "form_sticky":
            sim["form"] += missed
            home_uses += 1
            sim_form_events += 1
        elif kind == "repair":
            sim["repair"] += missed
            I, I0 = e[1], e[2]
            if cfg.placement == "sticky":
                wait_left, hour = e[3], e[4]
                # The sticky idle pool is what is left after forming every complete
                # home-block set, so at least one block is absent from it: condition
                # the uniform pool on that event.
                p_none = q ** I0 / max(q ** I0, p_some_block_absent(I0, B))
                p_fb = p_none * math.exp(-a_h[int(hour)] * wait_left / B)
                fallbacks += p_fb
                home_uses += 1 - p_fb
            elif quarter:
                mod["repair"] += q ** max(1, I // 4)
            else:
                mod["repair"] += q ** I
        elif kind == "refill":
            sim["refill"] += missed
            mod["refill"] += q ** (max(1, e[1] // 4) if quarter else e[1])
    if cfg.placement == "sticky":
        # A fallback leaves the phone caching a block that is not its home block
        # ("drift"); its next use in its home role downloads again. Balance of
        # drift created (fallbacks on non-drifted phones) and drift removed (home
        # uses of drifted phones) gives the drifted fraction d.
        d = fallbacks / max(1e-9, fallbacks + home_uses)
        mod["repair"] += fallbacks + (home_uses - sim_form_events) * d
        mod["form"] += sim_form_events * d
    scale = r["block_gb"] / max(1.0, r["delivered_tokens"]) * 1e6
    return {"sim_downloads": sim, "model_downloads": mod,
            "sim_gb_per_mtoken": sum(sim.values()) * scale,
            "model_gb_per_mtoken": sum(mod.values()) * scale,
            "check_gb_per_mtoken": r["gb_per_mtoken"]}


def job(args):
    policy, n, seed = args
    r = ps.run(policy, n_phones=n, seed=seed, trace=True)
    return policy, n, seed, predict(r, policy)


def main():
    seeds = [0, 1] if QUICK else [0, 1, 2, 3, 4]
    jobs = [(p, 1000, s) for p in POLS for s in seeds]
    jobs += [(p, n, s) for p in SCALE_POLS for n in (500, 2000, 4000) for s in seeds[:3]]
    with Pool(os.cpu_count()) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    out = {}
    for p, n, s, res in rows:
        out.setdefault(f"{p}@{n}", []).append(res)
    summary = {}
    for key, rs in out.items():
        sim = [x["sim_gb_per_mtoken"] for x in rs]
        mod = [x["model_gb_per_mtoken"] for x in rs]
        summary[key] = {
            "sim": statistics.mean(sim), "model": statistics.mean(mod),
            "rel_err": (statistics.mean(mod) - statistics.mean(sim)) / max(1e-9, statistics.mean(sim)),
            "sim_form": statistics.mean(x["sim_downloads"]["form"] for x in rs),
            "model_form": statistics.mean(x["model_downloads"]["form"] for x in rs),
            "sim_repair": statistics.mean(x["sim_downloads"]["repair"] + x["sim_downloads"]["refill"] for x in rs),
            "model_repair": statistics.mean(x["model_downloads"]["repair"] + x["model_downloads"]["refill"] for x in rs),
            "seeds": len(rs)}
        assert all(abs(x["sim_gb_per_mtoken"] - x["check_gb_per_mtoken"]) < 1e-6 for x in rs)
    json.dump(summary, open(os.path.join(OUT, "traffic_model.json"), "w"), indent=1)
    for key, v in sorted(summary.items()):
        print(f"{key:24s} sim={v['sim']:7.1f} model={v['model']:7.1f} err={v['rel_err']*100:+6.1f}%"
              f"  form {v['sim_form']:7.1f}/{v['model_form']:7.1f}"
              f"  repair {v['sim_repair']:7.1f}/{v['model_repair']:7.1f}")


if __name__ == "__main__":
    main()
