# Journal version (Elsevier `elsarticle`)

First target: **Future Generation Computer Systems** (Elsevier). Fallbacks, one at a
time: J. Parallel and Distributed Computing, Cluster Computing, Pervasive and Mobile
Computing, J. Grid Computing, Concurrency and Computation: Practice and Experience.

Build: `latexmk -pdf main.tex` in this directory.

Generated inputs (do not edit by hand):
- `../numbers.tex` from `sim/make_numbers.py` (results of `sim/experiments.py`)
- `model_numbers.tex`, `model_table.tex` from `sim/journal_numbers.py`
  (results of `sim/traffic_model.py`, the analytical shard-traffic model checked
  against the simulator: 10 policies x 5 seeds at 1,000 phones, 4 policies x 3 seeds
  at 500/2,000/4,000; worst error 12%, mean 5.6%)

`refs.bib` = `../references.bib` + 47 entries checked against Crossref / arXiv /
proceedings pages.

## Before submission (blocking)
Every blue `\Pending{...}` value must be replaced (`grep -n Pending main.tex`):
1. Study A (`bench/STUDY.md`): phones used, per-layer times, batching cost, prefill
   ratio, sustained speed and temperature, power, hop latency and downlink,
   predicted vs measured time per token for 1-4 phones (target < 15% error).
2. Re-run `sim/experiments.py` with the measured parameters (`PHONESIM_PARAMS`) and
   report both sets of headline numbers.
3. Study B (volunteer charging logs) if available; otherwise keep the sentence that
   availability is synthetic.
4. Zenodo DOI for the code release; confirm the generative-AI declaration wording.
5. Remove `review` from the class options only if the journal asks for a final layout;
   FGCS accepts single-column review format on first submission.
