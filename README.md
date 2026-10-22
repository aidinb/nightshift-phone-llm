# NightShift: batch LLM inference on charging smartphones

Paper, simulator and phone benchmark kit. All results in the current PDF come
from the simulator with **assumed** phone parameters (Table 1). The benchmark
kit exists so those assumptions can be replaced by measurements before submission.

## Layout
- `paper/` — `main.tex` (ACM acmart), `references.bib` (27 entries, checked),
  `numbers.tex` (generated, do not edit), `figures/` (generated), `main.pdf`
  (anonymous review build), `main-arxiv.pdf` (named preprint build).
- `sim/` — `phonesim.py` (discrete-event simulator, 7 policies), `experiments.py`,
  `figures.py`, `make_numbers.py`, `results/*.json`.
- `bench/` — scripts to run on Android phones in Termux.

## Rebuild everything
```bash
cd sim
python3 experiments.py          # ~minutes; --quick for 2 seeds
python3 figures.py              # writes ../paper/figures/*.pdf
python3 make_numbers.py         # writes ../paper/numbers.tex
cd ../paper
latexmk -pdf main.tex                                     # anonymous review PDF
latexmk -pdf -jobname=main-arxiv \
  -pdflatex='pdflatex %O "\def\arxiv{1}\input{%S}"' main.tex   # named preprint
```
Every number in the text is a macro from `numbers.tex`, so text and figures
always agree with `results/`.

## Replace assumptions with measurements
1. On each phone (Termux): `bench/01_setup_termux.sh`, then `02_bench_compute.sh`
   (llama-bench + llama-batched-bench), `03_bench_network.sh` (needs
   `echo_server.py` on a laptop on the same Wi-Fi), and follow `04_pipeline_rpc.md`
   for a real 2–4 phone pipeline over llama.cpp RPC.
2. Volunteers run `05_availability_logger.sh` for at least 14 days (consent form
   first; it logs only plugged/Wi-Fi/battery, no SSID names, no location).
3. Fit parameters:
   `python3 bench/fit_params.py --device phoneA/ --device phoneB/ --net net/ --out params.json`
   Check the field names in `batched.jsonl` (`pl`, `tg`, `t_tg`) against your
   llama.cpp version before trusting `batch_alpha`.
4. Convert logs: `python3 bench/trace_to_sessions.py logs/*.csv --tz-offset-h 3 > sessions.csv`
5. Rerun with them:
   `PHONESIM_PARAMS=params.json PHONESIM_TRACE=sessions.csv python3 experiments.py`,
   then figures, numbers, latexmk. Fill the red TODO table in §7 with the measured values.

## Before submission (author-only steps)
- Affiliation in `main.tex` (red `\TODO`), arXiv build only. Never put a personal email.
- Venue: EuroMLSys 2027 (workshop, usually due ~Feb), a NeurIPS/MLSys systems
  workshop, or HotMobile 2028. Check the current call and page limit; switch the
  `acmart` options if the venue uses another format.
- arXiv: account + cs.DC endorsement; upload `main.tex`, `numbers.tex`,
  `references.bib`, `main.bbl`, `figures/*.pdf`.
- Public artifact repo (sim + bench + results) and its link in the paper.
