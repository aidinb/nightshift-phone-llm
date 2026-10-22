# Phone study kit: what to run, who to ask, what they agree to

Two separate studies. Study A uses only your own phones; Study B needs volunteers.

## Study A: benchmarks on your own phones (1 afternoon)

Goal: replace the assumed speeds in Table 1 with measured ones. Aim for 4 phones
that span the RAM classes (6, 8, 12 and 16 GB if you can borrow them).

| Step | On which device | Command | Takes |
|---|---|---|---|
| 1 | each phone | install Termux from F-Droid, then `bash 01_setup_termux.sh` | 20 min |
| 2 | each phone, on charger, screen off | `bash 02_bench_compute.sh` | 30–60 min |
| 3 | laptop on same Wi-Fi | `python3 echo_server.py` | — |
| 4 | each phone | `bash 03_bench_network.sh LAPTOP_IP` | 5 min |
| 5 | 2–4 phones + laptop | follow `04_pipeline_rpc.md` | 1 h |
| 6 | laptop | copy each phone's `~/phonebench/` to `results/<phone-name>/`, then `python3 fit_params.py --device results/A --device results/B ... --net results/A --out params.json` | 5 min |

Write down for each phone: model, chip, RAM, Android version. Those go into the paper's
measured-parameters table. Note the room temperature: phones slow down when hot,
and the script keeps the *sustained* (slowest) speed on purpose.

## Study B: 14-day availability logs from volunteers

Goal: real charging and Wi-Fi patterns instead of the assumed night/day model.
Aim for 20 or more Android volunteers across different routines (students,
office workers, shift workers, parents). Fewer than 10 is too few to report.

The logger records, every 5 minutes, only four things: time, plugged in yes/no,
Wi-Fi connected yes/no, battery percent. No network names, no location, no app use,
no messages, no identity. Each phone gets a random ID.

### Ethics
Many venues ask whether a human-subjects study had ethics approval. If you have
any university or employer link, ask its ethics office whether this needs review;
it is minimal-risk and usually gets an exemption. If you have none, state the
consent process and the data minimisation in the paper's Ethics section (the
draft already has a paragraph for this). Do not start collecting before you decide.

### Message to send volunteers
> Hi! I'm researching whether phones that are charging overnight could together run
> AI models. I need real charging patterns. Would you install a small logger on your
> Android phone for 14 days? Every 5 minutes it notes only: the time, whether the phone
> is plugged in, whether Wi-Fi is connected, and the battery level. Nothing else: no
> location, no Wi-Fi names, no apps, no messages, and your name is never attached.
> It uses almost no battery. You can stop any time and ask me to delete your data.
> Setup takes 10 minutes and I'll help. Interested?

### Consent form (one per volunteer, keep a copy)
- **Study:** availability of charging smartphones for distributed computing (research
  paper by Aidin Bazarchi).
- **What is recorded:** every 5 minutes, a timestamp, plugged in (yes/no), Wi-Fi connected
  (yes/no), battery percentage. Nothing else.
- **Duration:** 14 days. Removing Termux or the scheduled job stops it at once.
- **Identity:** your data is stored under a random ID. The list linking IDs to names is
  kept separately and destroyed when collection ends.
- **Use:** aggregate statistics and an anonymised trace (shifted to start at day 0)
  may be published with the paper so others can reproduce it.
- **Withdrawal:** you may stop and ask for deletion at any time before publication,
  without giving a reason.
- **Time zone:** you will be asked only for your UTC offset, to align days.

I agree to take part: name ______________  date ________  signature ______________

### Running it
1. On the volunteer's phone: install Termux and Termux:API from F-Droid, copy
   `05_availability_logger.sh` to `~/bench/`, run the `termux-job-scheduler` line
   at the top of that file. Check `~/phonebench/availability.csv` gets a new line
   after 5 minutes.
2. Tell them to keep Termux from being battery-optimised (Settings > Apps > Termux >
   Battery > Unrestricted), or Android will stop the job.
3. After 14 days, collect the CSV, rename it `<random-id>.csv`, note the UTC offset.
4. `python3 trace_to_sessions.py --tz-offset-h <offset> logs/*.csv > sessions.csv`
5. From the paper folder's sim/:
   `PHONESIM_PARAMS=params.json PHONESIM_TRACE=sessions.csv python3 experiments.py`
   then `figures.py`, `make_numbers.py`, and rebuild the PDF.
