"""phonesim: a discrete-time simulator for pipeline-parallel LLM inference on a
pool of volunteer smartphones that join only while charging on Wi-Fi.

Everything that describes a phone (memory, per-layer speed, bandwidth) or a
user's charging habits is a PARAMETER in `Config`. The defaults are stated
assumptions, not measurements; `bench/` produces the measurements that should
replace them, and `load_sessions_csv` lets a real availability trace replace
the synthetic one.

Policies compared (all share the same fixed shard catalogue and per-phone
shard cache, so the comparison isolates placement and recovery; see POLICIES):

  restart      random placement; a departure loses every in-flight sequence
  replay       random groups of phones; a departure is repaired by recruiting
               a new phone and replaying the lost stage's KV cache
  cacheaware   replay, but each pipeline is formed from phones that already
               cache its blocks (the fair, cache-aware baseline)
  standby      replay + one dedicated warm standby per stage
  lifetime     replay + pipelines formed from phones with similar predicted
               session end, so one short-lived member does not end a pipeline
  consolidate  replay + a damaged pipeline donates its phones to repair others
  wait         cacheaware + a fixed home block per phone, and repairs wait
               briefly for a phone that already holds the block
  sticky       wait + lifetime grouping
  nightshift   sticky + consolidate (the design proposed in the paper)

Measured parameters: set PHONESIM_PARAMS=path/to/params.json (written by
bench/fit_params.py) to override Config defaults, and PHONESIM_TRACE=path.csv
(written by bench/trace_to_sessions.py) to replace the synthetic availability.
"""
from __future__ import annotations

import bisect
import csv
import json
import os
import math
import random
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

DAY = 86400.0
HOUR = 3600.0


@dataclass
class Config:
    # pool and horizon
    n_phones: int = 2000
    seed: int = 0
    history_days: int = 7            # used only to train the availability predictor
    tick_s: float = 10.0             # scheduler tick == failure-detection granularity

    # model: Llama-class 70B at 4-bit (assumed 0.5 GB per layer, GQA KV 4 KiB/token/layer)
    n_layers: int = 80
    layer_gb: float = 0.5
    kv_bytes_per_token_layer: int = 4096
    block_layers: int = 5            # fixed shard catalogue: 16 blocks of 5 layers

    # workload: batch (throughput) inference
    batch_seqs: int = 32             # sequences in flight per pipeline
    prompt_tokens: int = 512
    output_tokens: int = 256
    prefill_efficiency: float = 8.0  # prefill token costs 1/8 of a decode token
    batch_alpha: float = 0.1         # cost of a micro-batch of b tokens = t1 * (1 + alpha*(b-1))

    # network
    hop_latency_s: float = 0.060     # WAN; use 0.005 for a single LAN
    flash_load_gbps: float = 8.0     # Gbit/s reading a cached shard from local flash (1 GB/s)
    cache_blocks: int = 1            # blocks a phone may keep in flash (volunteer storage quota)
    hidden_bytes_per_token: int = 16384  # fp16 activation entering a stage (hidden size 8192)
    dl_median_mbps: float = 50.0
    dl_sigma: float = 0.6

    # phones (RAM GB, share of pool, usable fraction, ms per 70B layer per token)
    phone_classes: Tuple[Tuple[float, float, float, float], ...] = (
        (6.0, 0.10, 0.45, 30.0),
        (8.0, 0.40, 0.45, 18.0),
        (12.0, 0.35, 0.45, 12.0),
        (16.0, 0.15, 0.45, 10.0),
    )
    speed_sigma: float = 0.2
    power_active_w: float = 4.0      # assumed whole-phone draw while computing a stage
    power_wait_w: float = 1.0        # assumed draw while loading/waiting in a pipeline

    # synthetic availability (charging + Wi-Fi + screen off)
    night_prob: float = 0.85
    night_start_mean_h: float = 23.0
    night_start_sd_h: float = 1.0
    night_dur_mean_h: float = 7.0
    night_dur_sd_h: float = 1.5
    day_sessions_per_day: float = 1.5
    day_dur_median_min: float = 35.0
    day_dur_sigma: float = 0.8
    day_wifi_prob: float = 0.6

    # policy knobs (see POLICIES for the named presets)
    policy: str = "nightshift"
    placement: str = "sticky"        # random | lifetime | sticky (home block + lifetime)
    recovery: str = "replay"         # restart | replay
    consolidate: bool = True         # donate phones of the most damaged pipeline
    standbys: int = 0                # dedicated warm standbys per stage
    sticky_fallback_s: float = 300.0 # sticky: wait this long for a home-block phone before downloading
    lifetime_order: bool = True      # sticky: order phones by predicted stay (False = random)
    eval_start_h: float = 12.0       # evaluate a 24 h window starting at noon
    eval_hours: float = 24.0
    warmup_days: int = 2             # run this long first and discard it, so caches and
                                     # pipelines reach the policy's own steady state
    sessions_override: Optional[Dict[int, List[Tuple[float, float]]]] = None


POLICIES = {
    "restart":    dict(placement="random",   recovery="restart", consolidate=False, standbys=0),
    "replay":     dict(placement="random",   recovery="replay",  consolidate=False, standbys=0),
    "standby":    dict(placement="random",   recovery="replay",  consolidate=False, standbys=1),
    "lifetime":   dict(placement="lifetime", recovery="replay",  consolidate=False, standbys=0),
    "consolidate": dict(placement="random",  recovery="replay",  consolidate=True,  standbys=0),
    "cacheaware": dict(placement="cache",    recovery="replay",  consolidate=False, standbys=0),
    "wait":       dict(placement="sticky",   recovery="replay",  consolidate=False, standbys=0,
                       lifetime_order=False),
    "sticky":     dict(placement="sticky",   recovery="replay",  consolidate=False, standbys=0),
    "nightshift": dict(placement="sticky",   recovery="replay",  consolidate=True,  standbys=0),
    "nightshift_nowait": dict(placement="sticky", recovery="replay", consolidate=True,
                              standbys=0, sticky_fallback_s=0.0),
}


# --------------------------------------------------------------------------
# phones and availability


@dataclass
class Phone:
    pid: int
    usable_gb: float
    ms_per_layer: float
    dl_mbps: float
    sessions: List[Tuple[float, float]]
    cached: List[int] = field(default_factory=list)  # blocks in flash, most recent first
    home_block: int = 0
    role: str = "idle"               # idle | stage | standby | loading
    pipe: Optional[int] = None

    _starts: Optional[List[float]] = None

    def session_at(self, t: float) -> Optional[Tuple[float, float]]:
        if self._starts is None:
            self._starts = [s for s, _ in self.sessions]
        i = bisect.bisect_right(self._starts, t) - 1
        if i >= 0 and t < self.sessions[i][1]:
            return self.sessions[i]
        return None


def synth_sessions(cfg: Config, rng: random.Random, days: int) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    habit_start = rng.gauss(cfg.night_start_mean_h, cfg.night_start_sd_h)
    habit_dur = max(2.0, rng.gauss(cfg.night_dur_mean_h, cfg.night_dur_sd_h))
    for d in range(days):
        if rng.random() < cfg.night_prob:
            s = (d * 24 + habit_start + rng.gauss(0, 0.5)) * HOUR
            dur = max(0.5, rng.gauss(habit_dur, 0.75)) * HOUR
            out.append((s, s + dur))
        n_day = _poisson(rng, cfg.day_sessions_per_day)
        for _ in range(n_day):
            if rng.random() > cfg.day_wifi_prob:
                continue
            s = (d * 24 + rng.uniform(8, 21)) * HOUR
            dur = rng.lognormvariate(math.log(cfg.day_dur_median_min * 60), cfg.day_dur_sigma)
            out.append((s, s + dur))
    out.sort()
    merged: List[Tuple[float, float]] = []
    for s, e in out:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _poisson(rng: random.Random, lam: float) -> int:
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def load_sessions_csv(path: str) -> Dict[int, List[Tuple[float, float]]]:
    """Real trace: CSV with columns user_id,start_s,end_s (seconds from trace start)."""
    sessions: Dict[int, List[Tuple[float, float]]] = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            sessions.setdefault(int(row["user_id"]), []).append(
                (float(row["start_s"]), float(row["end_s"])))
    for v in sessions.values():
        v.sort()
    return sessions


def make_phones(cfg: Config, rng: random.Random) -> List[Phone]:
    days = cfg.history_days + cfg.warmup_days + 3
    phones = []
    weights = [c[1] for c in cfg.phone_classes]
    override = list(cfg.sessions_override.values()) if cfg.sessions_override else None
    for i in range(cfg.n_phones):
        ram, _, frac, ms = rng.choices(cfg.phone_classes, weights)[0]
        sessions = override[i % len(override)] if override else synth_sessions(cfg, rng, days)
        phones.append(Phone(
            pid=i,
            usable_gb=ram * frac,
            ms_per_layer=ms * rng.lognormvariate(0, cfg.speed_sigma),
            dl_mbps=cfg.dl_median_mbps * rng.lognormvariate(0, cfg.dl_sigma),
            sessions=sessions,
        ))
    return phones


class Predictor:
    """Predicts when a phone's current charging session ends, from that user's
    own history: the mean length of past sessions that began at a similar hour
    of the day (+/- 1.5 h), falling back to the pool-wide mean."""

    def __init__(self, phones: List[Phone], history_end: float):
        self.hist: Dict[int, List[Tuple[float, float]]] = {}
        allx = []
        for p in phones:
            h = [((s % DAY) / HOUR, e - s) for s, e in p.sessions if e <= history_end]
            self.hist[p.pid] = h
            allx += [d for _, d in h]
        self.global_mean = sum(allx) / len(allx) if allx else HOUR
        self._cache: Dict[Tuple[int, float], float] = {}

    def predicted_end(self, p: Phone, t: float) -> float:
        sess = p.session_at(t)
        if sess is None:
            return t
        s, _ = sess
        key = (p.pid, s)
        if key not in self._cache:
            hod = (s % DAY) / HOUR
            near = [d for h, d in self.hist[p.pid]
                    if min(abs(h - hod), 24 - abs(h - hod)) <= 1.5]
            self._cache[key] = s + (sum(near) / len(near) if near else self.global_mean)
        return max(t + 60.0, self._cache[key])


# --------------------------------------------------------------------------
# pipelines


@dataclass
class Pipeline:
    pid: int
    stages: List[Optional[int]]                 # phone id per block (None = vacant)
    standbys: List[List[int]] = field(default_factory=list)
    ready_at: List[float] = field(default_factory=list)  # when each stage is usable
    progress: float = 0.0                       # work units done per sequence (lockstep batch)
    stalled_until: float = 0.0


class Sim:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.phones = make_phones(cfg, self.rng)
        self.t0 = (cfg.history_days * 24 + cfg.eval_start_h) * HOUR
        self.t1 = self.t0 + cfg.eval_hours * HOUR
        self.t_start = self.t0 - cfg.warmup_days * DAY
        self.pred = Predictor(self.phones, self.t_start)  # trained on history only
        self.n_blocks = math.ceil(cfg.n_layers / cfg.block_layers)
        # Steady state: every phone already holds one block in flash from an
        # earlier night. Blocks are spread evenly over eligible phones; a
        # sticky policy keeps each phone on that "home" block for good.
        for i, p in enumerate(self.phones):
            p.home_block = i % self.n_blocks
            p.cached = [p.home_block]
        self.block_gb = cfg.block_layers * cfg.layer_gb
        seq_tokens = cfg.prompt_tokens + cfg.output_tokens
        self.kv_gb = (cfg.batch_seqs * seq_tokens * cfg.block_layers
                      * cfg.kv_bytes_per_token_layer) / 1e9
        self.need_gb = self.block_gb + self.kv_gb
        self.work_per_seq = cfg.prompt_tokens / cfg.prefill_efficiency + cfg.output_tokens
        self.pipes: Dict[int, Pipeline] = {}
        self.next_pipe = 0
        self.use_place = (cfg.placement == "lifetime"
                          or (cfg.placement == "sticky" and cfg.lifetime_order))
        self.sticky = cfg.placement == "sticky"
        self.cache_form = cfg.placement == "cache"
        self.act_bytes = 0.0
        self.served = set()
        self.tok_time_samples: List[float] = []
        self._seen = 0
        self._srng = random.Random(cfg.seed + 7919)   # sampling only; never perturbs the run
        self.k = cfg.standbys
        self.bytes_downloaded = 0.0
        self.consolidations = 0
        self.oracle_pipe_seconds = 0.0
        self.loss = {"load": 0.0, "replay": 0.0, "transfer": 0.0, "vacant": 0.0, "form": 0.0}
        # metrics
        self.delivered_tokens = 0.0
        self.lost_work = 0.0
        self.failures = 0
        self.standby_swaps = 0
        self.stage_seconds_running = 0.0
        self.stage_seconds_stalled = 0.0
        self.pipe_seconds_running = 0.0
        self.latency_samples: List[float] = []
        self.timeline: List[Tuple[float, int, int, float]] = []
        self._avail_t = -1.0
        self._avail: List[bool] = []
        self._vacant_since: Dict[int, float] = {}

    # ---- helpers
    def available(self, p: Phone, t: float) -> bool:
        if t != self._avail_t:
            self._avail_t = t
            self._avail = [q.session_at(t) is not None for q in self.phones]
        return self._avail[p.pid]

    def eligible(self, p: Phone) -> bool:
        return p.usable_gb >= self.need_gb

    def idle_pool(self, t: float) -> List[Phone]:
        return [p for p in self.phones
                if p.role == "idle" and self.eligible(p) and self.available(p, t)]

    def load_time(self, p: Phone, block: int) -> float:
        if block in p.cached:
            return self.block_gb * 8 / self.cfg.flash_load_gbps
        return self.block_gb * 8000 / p.dl_mbps

    def rank(self, pool: List[Phone], t: float) -> List[Phone]:
        if self.use_place:
            return sorted(pool, key=lambda p: -self.pred.predicted_end(p, t))
        pool = pool[:]
        self.rng.shuffle(pool)
        return pool

    def take_for_block(self, ranked: List[Phone], block: int) -> Optional[Phone]:
        if self.sticky:
            # home-block phones first (longest predicted stay wins), else
            # fall back to any phone, which then downloads the block
            for i, p in enumerate(ranked):
                if p.home_block == block:
                    return ranked.pop(i)
            return ranked.pop(0) if ranked else None
        """Prefer a phone that already caches this block (any policy), else the
        top-ranked one. For availability-aware placement, only accept a cached
        phone from the top of the ranking so caching does not override it."""
        if not ranked:
            return None
        window = ranked[: max(1, len(ranked) // 4)] if self.use_place else ranked
        for i, p in enumerate(window):
            if block in p.cached:
                return ranked.pop(ranked.index(p))
        return ranked.pop(0)

    def assign(self, p: Phone, role: str, pipe: int, block: int, t: float) -> float:
        p.role, p.pipe = role, pipe
        lt = self.load_time(p, block)
        self.served.add(p.pid)
        if block in p.cached:
            p.cached.remove(block)
        else:
            self.bytes_downloaded += self.block_gb
        p.cached.insert(0, block)
        del p.cached[max(1, self.cfg.cache_blocks):]
        return t + lt

    def release(self, pid: int):
        p = self.phones[pid]
        p.role, p.pipe = "idle", None

    # ---- pipeline performance
    def stage_time(self, p: Phone) -> float:
        cfg = self.cfg
        b = max(1.0, cfg.batch_seqs / self.n_blocks)
        return cfg.block_layers * p.ms_per_layer / 1000 * (1 + cfg.batch_alpha * (b - 1))

    def pipe_rate(self, pl: Pipeline) -> Tuple[float, float]:
        """(work units per second per sequence, per-token latency in seconds)."""
        cfg = self.cfg
        taus = [self.stage_time(self.phones[s]) for s in pl.stages]
        tok_latency = sum(taus) + len(taus) * cfg.hop_latency_s
        round_time = max(tok_latency, self.n_blocks * max(taus))
        # each round advances every sequence by one decode-equivalent unit
        return 1.0 / round_time, tok_latency

    def done_tokens(self, pl: Pipeline) -> float:
        cfg = self.cfg
        return cfg.prompt_tokens + max(
            0.0, pl.progress - cfg.prompt_tokens / cfg.prefill_efficiency)

    def replay_time(self, pl: Pipeline, p: Phone) -> float:
        cfg = self.cfg
        per_tok = cfg.block_layers * p.ms_per_layer / 1000 / cfg.prefill_efficiency
        return cfg.batch_seqs * self.done_tokens(pl) * per_tok

    def replay_transfer(self, pl: Pipeline, p: Phone) -> Tuple[float, float]:
        """(seconds, GB) to send the replacement the stage's input activations
        for every token so far, so it can rebuild the lost KV cache. They come
        from the upstream stage over the WAN; the replacement's download link
        is taken as the bottleneck."""
        gb = self.cfg.batch_seqs * self.done_tokens(pl) * self.cfg.hidden_bytes_per_token / 1e9
        return gb * 8000 / p.dl_mbps, gb

    # ---- scheduler actions
    def form_pipelines(self, t: float):
        if self.sticky:
            return self.form_sticky(t)
        if self.cache_form:
            return self.form_cached(t)
        ranked = self.rank(self.idle_pool(t), t)
        per_pipe = self.n_blocks * (1 + self.k)
        while len(ranked) >= per_pipe:
            pid = self.next_pipe
            self.next_pipe += 1
            # group: take the next per_pipe phones from the ranking so members
            # have similar predicted lifetimes (placement policy), or random ones
            group = ranked[:per_pipe]
            del ranked[:per_pipe]
            stages, ready, standbys = [], [], []
            for b in range(self.n_blocks):
                p = self.take_for_block(group, b)
                ready.append(self.assign(p, "stage", pid, b, t))
                stages.append(p.pid)
            for b in range(self.n_blocks):
                sb = []
                for _ in range(self.k):
                    p = self.take_for_block(group, b)
                    self.assign(p, "standby", pid, b, t)
                    sb.append(p.pid)
                standbys.append(sb)
            self.pipes[pid] = Pipeline(pid, stages, standbys, ready, 0.0, max(ready))
            self.loss["form"] += max(ready) - t

    def form_cached(self, t: float):
        """Cache-aware baseline: form as many pipelines as the idle pool
        allows; first give every pipeline phones that already cache each of
        its blocks (random order, no availability prediction), then fill the
        remaining stages from the leftover phones, which download. Nobody
        waits."""
        pool = self.rank(self.idle_pool(t), t)
        n_pipes = len(pool) // self.n_blocks
        if n_pipes == 0:
            return
        used = set()
        slots = [[None] * self.n_blocks for _ in range(n_pipes)]
        buckets: List[List[Phone]] = [[] for _ in range(self.n_blocks)]
        for p in pool:
            for b in p.cached:
                buckets[b].append(p)
        for b in range(self.n_blocks):
            it = iter(buckets[b])
            for i in range(n_pipes):
                for p in it:
                    if p.pid not in used:
                        slots[i][b] = p
                        used.add(p.pid)
                        break
        rest = [p for p in pool if p.pid not in used]
        for i in range(n_pipes):
            pid = self.next_pipe
            self.next_pipe += 1
            stages, ready = [], []
            for b in range(self.n_blocks):
                p = slots[i][b] or rest.pop(0)
                ready.append(self.assign(p, "stage", pid, b, t))
                stages.append(p.pid)
            self.pipes[pid] = Pipeline(pid, stages, [[] for _ in range(self.n_blocks)],
                                       ready, 0.0, max(ready))
            self.loss["form"] += max(ready) - t

    def form_sticky(self, t: float):
        """One pipeline per complete set of home blocks. Each block's idle
        phones are sorted by predicted stay, and the i-th pipeline takes the
        i-th phone of every block, so members of a pipeline are expected to
        leave at about the same time."""
        buckets: List[List[Phone]] = [[] for _ in range(self.n_blocks)]
        for p in self.rank(self.idle_pool(t), t):
            buckets[p.home_block].append(p)
        per = 1 + self.k
        while all(len(b) >= per for b in buckets):
            pid = self.next_pipe
            self.next_pipe += 1
            stages, ready, standbys = [], [], []
            for b in range(self.n_blocks):
                p = buckets[b].pop(0)
                ready.append(self.assign(p, "stage", pid, b, t))
                stages.append(p.pid)
                sb = []
                for _ in range(self.k):
                    q = buckets[b].pop(0)
                    self.assign(q, "standby", pid, b, t)
                    sb.append(q.pid)
                standbys.append(sb)
            self.pipes[pid] = Pipeline(pid, stages, standbys, ready, 0.0, max(ready))
            self.loss["form"] += max(ready) - t

    def handle_departures(self, t: float):
        for pl in list(self.pipes.values()):
            # standbys that left: drop them
            for b, sb in enumerate(pl.standbys):
                for s in list(sb):
                    if not self.available(self.phones[s], t):
                        sb.remove(s)
                        self.release(s)
            for b, s in enumerate(pl.stages):
                if s is not None and not self.available(self.phones[s], t):
                    self.failures += 1
                    self.release(s)
                    pl.stages[b] = None
                    if self.cfg.recovery == "restart":
                        self.lost_work += pl.progress * self.cfg.batch_seqs
                        pl.progress = 0.0
            if any(s is None for s in pl.stages):
                self.repair(pl, t)

    def repair(self, pl: Pipeline, t: float):
        pool = None
        for b, s in enumerate(pl.stages):
            if s is not None:
                continue
            ready = None
            if pl.standbys[b]:
                p = self.phones[pl.standbys[b].pop(0)]
                p.role = "stage"
                ready = t + self.block_gb * 8 / self.cfg.flash_load_gbps
                self.standby_swaps += 1
            else:
                if pool is None:
                    pool = self.rank(self.idle_pool(t), t)
                if self.sticky and not any(q.home_block == b for q in pool):
                    since = self._vacant_since.get(pl.pid, t)
                    if t - since < self.cfg.sticky_fallback_s:
                        self._vacant_since.setdefault(pl.pid, t)
                        pl.stalled_until = max(pl.stalled_until, t + self.cfg.tick_s)
                        continue
                p = self.take_for_block(pool, b)
                if p is None:
                    pl.stalled_until = max(pl.stalled_until, t + self.cfg.tick_s)
                    continue
                ready = self.assign(p, "stage", pl.pid, b, t)
            pl.stages[b] = p.pid
            self.loss["load"] += ready - t
            if self.cfg.recovery == "replay":
                rt = self.replay_time(pl, p)
                xt, xgb = self.replay_transfer(pl, p)
                self.act_bytes += xgb
                ready += xt + rt
                self.loss["replay"] += rt
                self.loss["transfer"] += xt
            pl.stalled_until = max(pl.stalled_until, ready)

    def dissolve(self, pid: int):
        pl = self.pipes.pop(pid)
        self.lost_work += pl.progress * self.cfg.batch_seqs
        for s in pl.stages:
            if s is not None:
                self.release(s)
        for sb in pl.standbys:
            for s in sb:
                self.release(s)
        self._vacant_since.pop(pid, None)

    def consolidate(self, t: float):
        """When pipelines have vacant stages that the idle pool cannot fill,
        dissolve the most damaged one (most vacancies, then least progress) and
        give its phones, which already hold blocks of the same catalogue, to the
        others. A donated phone loads its block from flash in seconds instead of
        downloading it, so a pool shrinking at dawn keeps as many complete
        pipelines as it can afford rather than many broken ones."""
        while True:
            vacant = [pl for pl in self.pipes.values()
                      if any(s is None for s in pl.stages)]
            if len(vacant) < 2:
                # a single broken pipeline: only dissolve it if the idle pool
                # cannot repair it, so its phones can join a new pipeline later
                return
            worst = max(vacant, key=lambda pl: (sum(s is None for s in pl.stages),
                                                -pl.progress))
            self.dissolve(worst.pid)
            self.consolidations += 1
            for pl in vacant:
                if pl.pid in self.pipes:
                    self.repair(pl, t)

    def refill_standbys(self, t: float):
        if self.k == 0:
            return
        pool = None
        for pl in self.pipes.values():
            for b, sb in enumerate(pl.standbys):
                while len(sb) < self.k:
                    if pool is None:
                        pool = self.rank(self.idle_pool(t), t)
                    p = self.take_for_block(pool, b)
                    if p is None:
                        return
                    self.assign(p, "standby", pl.pid, b, t)
                    sb.append(p.pid)

    def dissolve_starved(self, t: float):
        """A pipeline with a vacant stage for more than 10 minutes gives its
        phones back to the pool (its in-flight work is lost)."""
        for pid, pl in list(self.pipes.items()):
            if all(s is not None for s in pl.stages):
                self._vacant_since.pop(pid, None)
                continue
            since = self._vacant_since.setdefault(pid, t)
            if t - since > 600:
                self.lost_work += pl.progress * self.cfg.batch_seqs
                for s in pl.stages:
                    if s is not None:
                        self.release(s)
                for sb in pl.standbys:
                    for s in sb:
                        self.release(s)
                del self.pipes[pid]
                del self._vacant_since[pid]

    def _reset_metrics(self):
        """End of warm-up: keep the system state, zero every counter."""
        self.bytes_downloaded = self.act_bytes = 0.0
        self.consolidations = self.failures = self.standby_swaps = 0
        self.oracle_pipe_seconds = self.delivered_tokens = self.lost_work = 0.0
        self.stage_seconds_running = self.stage_seconds_stalled = 0.0
        self.pipe_seconds_running = 0.0
        self.loss = {k: 0.0 for k in self.loss}
        self.latency_samples, self.tok_time_samples, self._seen = [], [], 0
        self.served = {p.pid for p in self.phones if p.role != "idle"}
        self.timeline = []

    # ---- main loop
    def run(self) -> dict:
        cfg = self.cfg
        t = self.t_start
        measuring = cfg.warmup_days == 0
        while t < self.t1:
            if not measuring and t >= self.t0:
                self._reset_metrics()
                measuring = True
            self.handle_departures(t)
            if cfg.consolidate:
                self.consolidate(t)
            self.dissolve_starved(t)
            self.form_pipelines(t)
            self.refill_standbys(t)
            running = 0
            for pl in self.pipes.values():
                full = all(s is not None for s in pl.stages)
                if full and t >= pl.stalled_until:
                    rate, lat = self.pipe_rate(pl)
                    pl.progress += rate * cfg.tick_s
                    running += 1
                    self.stage_seconds_running += self.n_blocks * cfg.tick_s
                    # uniform reservoir sample over all running pipeline-ticks
                    self._seen += 1
                    if len(self.latency_samples) < 50000:
                        self.latency_samples.append(lat)
                        self.tok_time_samples.append(1.0 / rate)
                    else:
                        j = self._srng.randrange(self._seen)
                        if j < 50000:
                            self.latency_samples[j] = lat
                            self.tok_time_samples[j] = 1.0 / rate
                    while pl.progress >= self.work_per_seq:
                        pl.progress -= self.work_per_seq
                        self.delivered_tokens += cfg.batch_seqs * cfg.output_tokens
                else:
                    if not full:
                        self.loss["vacant"] += cfg.tick_s
                    self.stage_seconds_stalled += sum(
                        1 for s in pl.stages if s is not None) * cfg.tick_s
            self.pipe_seconds_running += running * cfg.tick_s
            avail = sum(1 for p in self.phones if self.available(p, t) and self.eligible(p))
            # oracle: every eligible available phone in a complete pipeline, instantly
            self.oracle_pipe_seconds += (avail // self.n_blocks) * cfg.tick_s
            if t >= self.t0 and int((t - self.t0) // cfg.tick_s) % 30 == 0:
                self.timeline.append(((t - self.t0) / HOUR, avail, running,
                                      self.delivered_tokens))
            t += cfg.tick_s
        secs = cfg.eval_hours * HOUR
        busy = self.stage_seconds_running + self.stage_seconds_stalled
        lat = sorted(self.latency_samples)
        tok = sorted(self.tok_time_samples)
        return {
            "policy": cfg.policy,
            "loss_pipe_s": dict(self.loss),
            "consolidations": self.consolidations,
            "gb_downloaded": self.bytes_downloaded,
            "gb_per_mtoken": self.bytes_downloaded / max(1.0, self.delivered_tokens) * 1e6,
            "act_gb_per_mtoken": self.act_bytes / max(1.0, self.delivered_tokens) * 1e6,
            "total_gb_per_mtoken": (self.bytes_downloaded + self.act_bytes)
                                   / max(1.0, self.delivered_tokens) * 1e6,
            "gb_per_serving_phone": (self.bytes_downloaded + self.act_bytes)
                                    / max(1, len(self.served)),
            "oracle_pipe_frac": self.pipe_seconds_running / max(1.0, self.oracle_pipe_seconds),
            "standbys": self.k,
            "seed": cfg.seed,
            "tokens_per_s": self.delivered_tokens / secs,
            "joules_per_token": (self.stage_seconds_running * cfg.power_active_w
                                 + self.stage_seconds_stalled * cfg.power_wait_w)
                                / max(1.0, self.delivered_tokens),
            "tokens_per_s_per_1k_phones": self.delivered_tokens / secs * 1000 / cfg.n_phones,
            "failures": self.failures,
            "standby_swaps": self.standby_swaps,
            "lost_work_units": self.lost_work,   # decode-token equivalents (prefill = 1/8)
            "useful_stage_frac": self.stage_seconds_running / busy if busy else 0.0,
            "mean_running_pipes": self.pipe_seconds_running / secs,
            "pass_latency_p50_s": lat[len(lat) // 2] if lat else float("nan"),
            "token_time_p50_s": tok[len(tok) // 2] if tok else float("nan"),
            "eligible_frac": sum(self.eligible(p) for p in self.phones) / len(self.phones),
            "timeline": self.timeline,
        }


def env_overrides() -> dict:
    """Config overrides from measurements (see module docstring)."""
    out: dict = {}
    if os.environ.get("PHONESIM_PARAMS"):
        with open(os.environ["PHONESIM_PARAMS"]) as f:
            out.update(json.load(f).get("config", {}))
        if "phone_classes" in out:
            out["phone_classes"] = tuple(tuple(c) for c in out["phone_classes"])
    if os.environ.get("PHONESIM_TRACE"):
        out["sessions_override"] = load_sessions_csv(os.environ["PHONESIM_TRACE"])
    return out


def run(policy: str = "nightshift", **kw) -> dict:
    knobs = env_overrides()
    knobs.update(POLICIES[policy])
    knobs.update(kw)
    return Sim(replace(Config(), policy=policy, **knobs)).run()
