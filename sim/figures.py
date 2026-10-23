"""Draws the paper's figures from results/*.json into ../paper/figures/.
Usage: python3 figures.py"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
OUT = os.path.join(HERE, "..", "paper", "figures")

# reference palette (light mode): slot 1 blue = ours, slot 2 orange = baseline
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
NEUTRAL_BAR = "#b9b8b2"
PURPLE = "#8f5bd6"
SERIES = {"replay": (ORANGE, "Replay"), "nightshift": (BLUE, "NightShift"),
          "cacheaware": (AQUA, "Cache-aware"), "consolidate": (PURPLE, "Consolidate")}

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8.5,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "lines.linewidth": 2, "legend.frameon": False, "legend.fontsize": 7,
    "savefig.bbox": "tight", "savefig.dpi": 300, "pdf.fonttype": 42,
})


def load(name):
    return json.load(open(os.path.join(RES, name)))


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"))
    plt.close(fig)


def fig_timeline():
    tl = load("timeline.json")
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(3.4, 3.0), sharex=True,
                                 gridspec_kw={"height_ratios": [1, 1.3]})
    hrs = [12 + r[0] for r in tl["nightshift"]]
    a1.plot(hrs, [r[1] for r in tl["nightshift"]], color=AQUA)
    a1.set_ylabel("Phones available")
    a1.set_title("Charging + Wi-Fi availability (1,000 phones)", loc="left", color=INK)
    a2.plot(hrs, [r[1] // 16 for r in tl["nightshift"]], color=MUTED, linewidth=1,
            linestyle=(0, (3, 2)), label="Upper bound (all available, instantly)")
    for pol in ("replay", "nightshift"):
        c, lab = SERIES[pol]
        a2.plot([12 + r[0] for r in tl[pol]], [r[2] for r in tl[pol]], color=c, label=lab)
    a2.set_ylabel("Pipelines running")
    a2.set_xlabel("Local time (h)")
    ticks = list(range(12, 37, 4))
    a2.set_xticks(ticks, [f"{t % 24:02d}" for t in ticks])
    a2.legend(loc="upper left", handlelength=1.6)
    save(fig, "timeline")


def fig_policies():
    pol = load("policies.json")
    order = ["restart", "replay", "cacheaware", "standby", "lifetime", "consolidate",
             "wait", "sticky", "nightshift_nowait", "nightshift"]
    names = {"restart": "Restart", "replay": "Replay", "cacheaware": "Cache-aware",
             "standby": "Replay + standby",
             "lifetime": "Replay + lifetime groups", "consolidate": "Replay + consolidate",
             "wait": "Cache-aware + home block, wait",
             "sticky": "  + lifetime groups (sticky)",
             "nightshift_nowait": "NightShift without the wait",
             "nightshift": "NightShift (sticky + consol.)"}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.0, 2.6), sharey=True)
    y = list(range(len(order)))[::-1]
    colors = [BLUE if p == "nightshift" else NEUTRAL_BAR for p in order]
    for ax, key, xlab, fmt in (
            (a1, "tokens_per_s_per_1k_phones", "Tokens/s per 1,000 phones (higher is better)", "{:.0f}"),
            (a2, "total_gb_per_mtoken", "GB per 1M tokens, shards + activations (lower is better)", "{:.0f}")):
        vals = [pol[p][key]["mean"] for p in order]
        sds = [pol[p][key]["sd"] for p in order]
        if key == "total_gb_per_mtoken":
            act = [pol[p]["act_gb_per_mtoken"]["mean"] for p in order]
            ax.barh(y, [v - a for v, a in zip(vals, act)], color=colors, height=0.66,
                    edgecolor="white", linewidth=1)
            ax.barh(y, act, left=[v - a for v, a in zip(vals, act)], color=GRID, height=0.66,
                    edgecolor="white", linewidth=1, xerr=sds,
                    error_kw={"elinewidth": 0.8, "ecolor": INK2, "capsize": 1.5})
        else:
            ax.barh(y, vals, xerr=sds, color=colors, height=0.66, edgecolor="white",
                    linewidth=1, error_kw={"elinewidth": 0.8, "ecolor": INK2, "capsize": 1.5})
        for yi, v, sd in zip(y, vals, sds):
            ax.text(v + sd + max(vals) * 0.015, yi, fmt.format(v), va="center",
                    fontsize=6.5, color=INK)
        ax.set_xlabel(xlab)
        ax.set_xlim(0, max(v + s for v, s in zip(vals, sds)) * 1.18)
        ax.grid(axis="y", visible=False)
    a1.set_yticks(y, [names[p] for p in order])
    save(fig, "policies")


PARAM_LABEL = {
    "prefill_efficiency": "Prefill cost ratio (decode/prefill)",
    "day_dur_median_min": "Daytime charging session, median (min)",
    "night_prob": "Share of nights a phone charges",
    "batch_seqs": "Sequences per pipeline",
    "hop_latency_s": "One-way hop latency (s)",
    "n_phones": "Pool size (phones)",
}


def fig_sweeps():
    sw = load("sweeps.json")
    params = list(PARAM_LABEL)
    fig, axes = plt.subplots(2, 3, figsize=(7.0, 3.6))
    for ax, param in zip(axes.flat, params):
        xs = sorted(sw[param], key=float)
        for pol in ("replay", "nightshift"):
            c, lab = SERIES[pol]
            m = [sw[param][x][pol]["tokens_per_s_per_1k_phones"]["mean"] for x in xs]
            ax.plot([float(x) for x in xs], m, color=c, marker="o", markersize=3.5,
                    markeredgecolor="white", markeredgewidth=0.8, label=lab)
        ax.set_xlabel(PARAM_LABEL[param])
        if param in ("prefill_efficiency", "n_phones"):
            ax.set_xscale("log", base=2)
            ax.set_xticks([float(x) for x in xs], [f"{float(x):g}" for x in xs])
            ax.minorticks_off()
        ax.set_ylim(bottom=0)
    for ax in axes[:, 0]:
        ax.set_ylabel("Tokens/s per 1k phones")
    axes[0, 0].legend(loc="lower right")
    fig.tight_layout(h_pad=1.2, w_pad=1.0)
    save(fig, "sweeps")


def fig_latency():
    sw = load("sweeps.json")["hop_latency_s"]
    xs = sorted(sw, key=float)
    fig, ax = plt.subplots(figsize=(3.4, 1.9))
    for pol in ("replay", "nightshift"):
        c, lab = SERIES[pol]
        ax.plot([float(x) * 1000 for x in xs],
                [sw[x][pol]["token_time_p50_s"]["mean"] for x in xs],
                color=c, marker="o", markersize=3.5, markeredgecolor="white", label=lab)
    ax.set_xlabel("One-way hop latency (ms)")
    ax.set_ylabel("Median time per token (s)")
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left")
    save(fig, "latency")


def fig_scale():
    sw = load("sweeps.json")["n_phones"]
    xs = sorted(sw, key=float)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(3.4, 2.0))
    for pol in ("replay", "cacheaware", "consolidate", "nightshift"):
        c, lab = SERIES[pol]
        kw = dict(color=c, marker="o", markersize=3.5, markeredgecolor="white", label=lab)
        a1.plot([float(x) for x in xs], [sw[x][pol]["tokens_per_s_per_1k_phones"]["mean"] for x in xs], **kw)
        a2.plot([float(x) for x in xs], [sw[x][pol]["total_gb_per_mtoken"]["mean"] for x in xs], **kw)
    for ax, lab in ((a1, "Tokens/s per 1k phones"), (a2, "GB downloaded per 1M tokens")):
        ax.set_xscale("log", base=2)
        ax.set_xticks([float(x) for x in xs], [f"{int(float(x)) // 1000}k" if float(x) >= 1000 else x for x in xs])
        ax.minorticks_off()
        ax.set_xlabel("Pool size (phones)")
        ax.set_title(lab, loc="left", color=INK, fontsize=7.5)
        ax.set_ylim(bottom=0)
    a2.set_yscale("log")
    a2.set_ylim(10, 1000)
    from matplotlib.ticker import FixedLocator, FixedFormatter, NullLocator
    a2.yaxis.set_major_locator(FixedLocator([10, 30, 100, 300, 1000]))
    a2.yaxis.set_major_formatter(FixedFormatter(["10", "30", "100", "300", "1000"]))
    a2.yaxis.set_minor_locator(NullLocator())
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=4, fontsize=6.3, handlelength=1.2,
               bbox_to_anchor=(0.5, -0.04))
    fig.tight_layout(w_pad=1.2, rect=(0, 0.08, 1, 1))
    save(fig, "scale")


def fig_tradeoff():
    """Left: traffic vs how many blocks a phone may keep in flash.
    Right: throughput vs traffic; NightShift's wait time traces a curve."""
    from matplotlib.ticker import FixedLocator, FixedFormatter, NullLocator
    sw = load("sweeps.json")
    pol = load("policies.json")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(3.4, 2.3))
    cb = sw["cache_blocks"]
    xs = sorted(cb, key=float)
    for p in ("replay", "cacheaware", "consolidate", "nightshift"):
        c, lab = SERIES[p]
        a1.plot(range(len(xs)), [cb[x][p]["total_gb_per_mtoken"]["mean"] for x in xs],
                color=c, marker="o", markersize=3.5, markeredgecolor="white", label=lab)
    a1.set_xticks(range(len(xs)), xs)
    a1.set_ylim(0, None)
    a1.set_xlabel("Blocks a phone may cache")
    a1.set_ylabel("GB per 1M tokens")
    fw = sw["sticky_fallback_s"]
    ws = sorted(fw, key=float)
    gx = [fw[w]["nightshift"]["total_gb_per_mtoken"]["mean"] for w in ws]
    ty = [fw[w]["nightshift"]["tokens_per_s_per_1k_phones"]["mean"] for w in ws]
    a2.plot(gx, ty, color=BLUE, marker="o", markersize=3.5, markeredgecolor="white")
    for x, y, w in zip(gx, ty, ws):
        spot = {0.0: ((-5, -2), "right"), 60.0: ((0, 6), "center"), 600.0: ((2, -9), "left")}
        if float(w) in spot:
            off, ha = spot[float(w)]
            a2.annotate(f"wait {float(w):.0f}s", (x, y), textcoords="offset points",
                        xytext=off, ha=ha, fontsize=5.8, color=INK2)
    for p in ("replay", "cacheaware", "consolidate"):
        c, lab = SERIES[p]
        a2.plot([pol[p]["total_gb_per_mtoken"]["mean"]], [pol[p]["tokens_per_s_per_1k_phones"]["mean"]],
                linestyle="none", marker="s", markersize=4, color=c, markeredgecolor="white")
    a2.set_xscale("log")
    ticks = [50, 100, 200, 400]
    a2.xaxis.set_major_locator(FixedLocator(ticks))
    a2.xaxis.set_major_formatter(FixedFormatter([str(t) for t in ticks]))
    a2.xaxis.set_minor_locator(NullLocator())
    a2.set_xlabel("GB per 1M tokens")
    a2.set_ylabel("Tokens/s per 1k phones")
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, fontsize=6.3, handlelength=1.2,
               bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(w_pad=1.0, rect=(0, 0.13, 1, 1))
    save(fig, "tradeoff")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for f in (fig_timeline, fig_policies, fig_sweeps, fig_latency, fig_scale, fig_tradeoff):
        f()
        print("drew", f.__name__)
