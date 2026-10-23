"""Writes ../paper/numbers.tex: every number quoted in the paper text, as a
LaTeX macro computed from results/*.json, so text and figures cannot drift."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
R = lambda n: json.load(open(os.path.join(HERE, "results", n)))  # noqa: E731
pol, sw, tl = R("policies.json"), R("sweeps.json"), R("timeline.json")
m = lambda p, k: pol[p][k]["mean"]  # noqa: E731

macros = {}
def put(name, val, fmt="{:.0f}"):
    macros[name] = fmt.format(val)

TAGS = [("restart", "Restart"), ("replay", "Replay"), ("cacheaware", "CA"),
        ("standby", "Standby"), ("lifetime", "Lifetime"), ("consolidate", "Consol"),
        ("wait", "Wait"), ("sticky", "Sticky"), ("nightshift_nowait", "NSNoWait"),
        ("nightshift", "NS")]
for p, tag in TAGS:
    put(f"Tput{tag}", m(p, "tokens_per_s_per_1k_phones"))
    put(f"GB{tag}", m(p, "total_gb_per_mtoken"))           # shards + activations
    put(f"Shard{tag}", m(p, "gb_per_mtoken"))
    put(f"Act{tag}", m(p, "act_gb_per_mtoken"))
    put(f"PhoneGB{tag}", m(p, "gb_per_serving_phone"), "{:.1f}")
    d = pol[p]["vs_replay"]["tokens_per_s_per_1k_phones"]
    put(f"DiffRep{tag}", d["mean"], "{:+.1f}")
    put(f"CIRep{tag}", d["ci95"], "{:.1f}")
    d = pol[p]["vs_consolidate"]["tokens_per_s_per_1k_phones"]
    put(f"DiffCons{tag}", d["mean"], "{:+.1f}")
    put(f"CICons{tag}", d["ci95"], "{:.1f}")
    put(f"TputSD{tag}", pol[p]["tokens_per_s_per_1k_phones"]["sd"], "{:.1f}")
    put(f"Oracle{tag}", 100 * m(p, "oracle_pipe_frac"))
    put(f"Fail{tag}", m(p, "failures"))
    put(f"Useful{tag}", 100 * m(p, "useful_stage_frac"))
    put(f"J{tag}", m(p, "joules_per_token"), "{:.0f}")
    put(f"Lat{tag}", m(p, "token_time_p50_s"), "{:.1f}")
pct = lambda a, b: 100 * (a / b - 1)  # noqa: E731
T = lambda p: m(p, "tokens_per_s_per_1k_phones")  # noqa: E731
G = lambda p: m(p, "total_gb_per_mtoken")  # noqa: E731
put("NSvsReplayPct", pct(T("nightshift"), T("replay")), "{:+.0f}")
put("NSvsConsolPct", pct(T("nightshift"), T("consolidate")), "{:+.0f}")
put("NSbehindConsolPct", -pct(T("nightshift"), T("consolidate")), "{:.0f}")
put("NSvsCAPct", pct(T("nightshift"), T("cacheaware")), "{:+.0f}")
put("CAvsReplayPct", pct(T("cacheaware"), T("replay")), "{:+.0f}")
put("WaitvsCAPct", pct(T("wait"), T("cacheaware")), "{:+.0f}")
put("GBRatioCA", G("cacheaware") / G("nightshift"))
put("GBRatioConsol", G("consolidate") / G("nightshift"))
put("ShardRatio", m("replay", "gb_per_mtoken") / m("nightshift", "gb_per_mtoken"))
put("TputGainPct", 100 * (m("nightshift", "tokens_per_s_per_1k_phones") / m("replay", "tokens_per_s_per_1k_phones") - 1))
ratio = G("replay") / max(1e-9, G("nightshift"))
put("GBRatio", ratio, "{:.0f}" if ratio < 1000 else "{:.0e}")
put("StandbyDropPct", 100 * (1 - m("standby", "tokens_per_s_per_1k_phones") / m("replay", "tokens_per_s_per_1k_phones")))
put("RestartVsReplayPct", 100 * (m("restart", "tokens_per_s_per_1k_phones") / m("replay", "tokens_per_s_per_1k_phones") - 1), "{:+.0f}")
put("EligiblePct", 100 * m("nightshift", "eligible_frac"))

# diurnal: share of tokens delivered 22:00-08:00 (hours 10..20 after noon)
t = tl["nightshift"]
def tokens_at(h):
    best = t[0]
    for r in t:
        if r[0] <= h:
            best = r
    return best[3]
total = t[-1][3]
put("NightSharePct", 100 * (tokens_at(20) - tokens_at(10)) / max(1, total))
avail = [r[1] for r in t]
put("PeakAvail", max(avail))
put("MinAvail", min(avail))
put("PeakPipes", max(r[2] for r in t))

h = sw["hop_latency_s"]
put("LatLAN", h["0.005"]["nightshift"]["token_time_p50_s"]["mean"], "{:.1f}")
put("LatWAN", h["0.06"]["nightshift"]["token_time_p50_s"]["mean"], "{:.1f}")
put("LatSlow", h["0.12"]["nightshift"]["token_time_p50_s"]["mean"], "{:.1f}")
for param, key in [("day_dur_median_min", "DayDur"), ("night_prob", "Night"),
                   ("prefill_efficiency", "Prefill"), ("n_phones", "Pool"),
                   ("batch_seqs", "Batch"), ("hop_latency_s", "Hop")]:
    vals = sorted(sw[param], key=float)
    for pname, ptag in (("replay", "Replay"), ("nightshift", "NS")):
        lo = sw[param][vals[0]][pname]["tokens_per_s_per_1k_phones"]["mean"]
        hi = sw[param][vals[-1]][pname]["tokens_per_s_per_1k_phones"]["mean"]
        put(f"Sw{key}Lo{ptag}", lo)
        put(f"Sw{key}Hi{ptag}", hi)

# total traffic, replay / nightshift, across every sweep setting that runs both
ratios = [sw[pr][v]["replay"]["total_gb_per_mtoken"]["mean"]
          / sw[pr][v]["nightshift"]["total_gb_per_mtoken"]["mean"]
          for pr in sw for v in sw[pr] if "replay" in sw[pr][v]]
put("GBRatioMin", min(ratios))
put("GBRatioMax", max(ratios))
pool = sw["n_phones"]
for v, tag in (("500", "Small"), ("4000", "Large")):
    for pname, ptag in (("replay", "Replay"), ("nightshift", "NS")):
        put(f"Pool{tag}GB{ptag}", pool[v][pname]["total_gb_per_mtoken"]["mean"])
    pt = lambda p: pool[v][p]["tokens_per_s_per_1k_phones"]["mean"]  # noqa: E731
    pg = lambda p: pool[v][p]["total_gb_per_mtoken"]["mean"]  # noqa: E731
    put(f"Pool{tag}GainPct", pct(pt("nightshift"), pt("replay")), "{:+.0f}")
    put(f"Pool{tag}VsConsolPct", pct(pt("nightshift"), pt("consolidate")), "{:+.0f}")
    put(f"Pool{tag}GBRatio", pg("replay") / pg("nightshift"))
    put(f"Pool{tag}GBRatioCA", pg("cacheaware") / pg("nightshift"))
for pname, ptag in (("cacheaware", "CA"), ("consolidate", "Consol")):
    put(f"SwPoolLo{ptag}", pool["500"][pname]["tokens_per_s_per_1k_phones"]["mean"])
    put(f"SwPoolHi{ptag}", pool["4000"][pname]["tokens_per_s_per_1k_phones"]["mean"])
cb = sw["cache_blocks"]
for pname, ptag in (("replay", "Replay"), ("cacheaware", "CA"), ("consolidate", "Consol"),
                    ("nightshift", "NS")):
    put(f"CacheFull{ptag}", cb["16"][pname]["total_gb_per_mtoken"]["mean"])
    put(f"CacheFullTput{ptag}", cb["16"][pname]["tokens_per_s_per_1k_phones"]["mean"])
put("CacheFullRatioCA", cb["16"]["cacheaware"]["total_gb_per_mtoken"]["mean"]
    / cb["16"]["nightshift"]["total_gb_per_mtoken"]["mean"])
fw = sw["sticky_fallback_s"]
for w, tag in (("0.0", "Zero"), ("60.0", "Sixty"), ("600.0", "Ten")):
    put(f"Wait{tag}Tput", fw[w]["nightshift"]["tokens_per_s_per_1k_phones"]["mean"])
    put(f"Wait{tag}GB", fw[w]["nightshift"]["total_gb_per_mtoken"]["mean"])
put("ConsolGainPct", 100 * (m("consolidate", "tokens_per_s_per_1k_phones") / m("replay", "tokens_per_s_per_1k_phones") - 1), "{:+.0f}")
put("StickyGainPct", 100 * (m("sticky", "tokens_per_s_per_1k_phones") / m("replay", "tokens_per_s_per_1k_phones") - 1), "{:+.0f}")
put("FailDropPct", 100 * (1 - m("nightshift", "failures") / m("replay", "failures")))

# ranges for prose and figure descriptions
BASE = ["restart", "replay", "cacheaware", "standby", "lifetime", "consolidate"]
put("GBBaseMin", min(G(p) for p in BASE))
put("GBBaseMax", max(G(p) for p in BASE))
put("GBRatioBaseMin", min(G(p) for p in BASE) / G("nightshift"), "{:.0f}")
put("GBRatioBaseMax", max(G(p) for p in BASE) / G("nightshift"), "{:.0f}")
ALLP = [p for p, _ in TAGS]
put("TputMin", min(T(p) for p in ALLP))
put("TputMax", max(T(p) for p in ALLP))
d = pol["restart"]["vs_replay"]["tokens_per_s_per_1k_phones"]
put("CIRepRestartPct", 100 * d["ci95"] / T("replay"), "{:.1f}")
TRI = ["replay", "cacheaware", "consolidate"]
put("GBTriMin", min(G(p) for p in TRI))
put("GBTriMax", max(G(p) for p in TRI))
for v, tag in (("1", "One"), ("16", "Full")):
    put(f"CacheTri{tag}Min", min(cb[v][p]["total_gb_per_mtoken"]["mean"] for p in TRI))
    put(f"CacheTri{tag}Max", max(cb[v][p]["total_gb_per_mtoken"]["mean"] for p in TRI))
put("CacheNSMin", min(cb[v]["nightshift"]["total_gb_per_mtoken"]["mean"] for v in cb))
put("CacheNSMax", max(cb[v]["nightshift"]["total_gb_per_mtoken"]["mean"] for v in cb))
pv = sorted(pool, key=float)
put("PoolTputBaseMin", min(pool[v][p]["tokens_per_s_per_1k_phones"]["mean"] for v in pv for p in TRI))
put("PoolTputBaseMax", max(pool[v][p]["tokens_per_s_per_1k_phones"]["mean"] for v in pv for p in TRI))
put("PoolGBBaseMin", min(pool[v][p]["total_gb_per_mtoken"]["mean"] for v in pv for p in TRI))
put("PoolGBBaseMax", max(pool[v][p]["total_gb_per_mtoken"]["mean"] for v in pv for p in TRI))
cross = [v for v in pv if pool[v]["nightshift"]["tokens_per_s_per_1k_phones"]["mean"]
         >= pool[v]["consolidate"]["tokens_per_s_per_1k_phones"]["mean"]]
put("PoolCross", int(cross[0]) if cross else 0, "{:,}")
gains = {(pr, v): pct(sw[pr][v]["nightshift"]["tokens_per_s_per_1k_phones"]["mean"],
                      sw[pr][v]["replay"]["tokens_per_s_per_1k_phones"]["mean"])
         for pr in sw for v in sw[pr] if "replay" in sw[pr][v]}
put("SwGainMin", min(gains.values()), "{:+.0f}")
put("SwGainMax", max(gains.values()), "{:+.0f}")
nv = sorted(sw["night_prob"], key=float)
put("SwNightLoGainPct", gains[("night_prob", nv[0])], "{:+.0f}")
put("SwNightHiGainPct", gains[("night_prob", nv[-1])], "{:+.0f}")
dv = sorted(sw["day_dur_median_min"], key=float)
put("DayGainPct", pct(sw["day_dur_median_min"][dv[-1]]["nightshift"]["tokens_per_s_per_1k_phones"]["mean"],
                      sw["day_dur_median_min"][dv[0]]["nightshift"]["tokens_per_s_per_1k_phones"]["mean"]), "{:+.0f}")
hv = sorted(h, key=float)
put("LatMinFig", min(h[v][p]["token_time_p50_s"]["mean"] for v in hv for p in h[v]), "{:.1f}")
put("LatMaxFig", max(h[v][p]["token_time_p50_s"]["mean"] for v in hv for p in h[v]), "{:.1f}")
put("PassLAN", h["0.005"]["nightshift"]["pass_latency_p50_s"]["mean"], "{:.1f}")
put("PassWAN", h["0.06"]["nightshift"]["pass_latency_p50_s"]["mean"], "{:.1f}")

meta = R("meta.json")
put("Seeds", len(meta["seeds"]))
put("SweepSeeds", len(meta.get("sweep_seeds", meta["seeds"])))
put("NPhones", meta["n_phones"], "{:,}")

out = os.path.join(HERE, "..", "paper", "numbers.tex")
with open(out, "w") as f:
    f.write("% generated by sim/make_numbers.py; do not edit\n")
    for k, v in sorted(macros.items()):
        f.write(f"\\newcommand{{\\{k}}}{{{v.replace(',', '{,}')}}}\n")
print(f"wrote {len(macros)} macros to {out}")
for k in sorted(macros):
    print(k, macros[k])
