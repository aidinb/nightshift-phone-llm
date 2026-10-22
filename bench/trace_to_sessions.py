#!/usr/bin/env python3
"""Convert availability logs from 05_availability_logger.sh into the
simulator's session CSV (user_id,start_s,end_s, seconds from local midnight
of the first day in the trace).

    python3 trace_to_sessions.py --tz-offset-h 3 phone1.csv phone2.csv ... > sessions.csv

A phone counts as available while it is plugged in AND on Wi-Fi. A gap longer
than --max-gap-min between samples (phone off, logger killed) ends a session.
Volunteers' files carry no identity: each file becomes one anonymous user id.
"""
import argparse
import csv
import sys

DAY = 86400


def sessions(path, max_gap):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append((int(r["ts"]), r["plugged"] == "1" and r["wifi_ssid_present"] == "1"))
    rows.sort()
    out, start, prev = [], None, None
    for ts, up in rows:
        if start is not None and (not up or ts - prev > max_gap):
            out.append((start, prev))
            start = None
        if up and start is None:
            start = ts
        prev = ts
    if start is not None:
        out.append((start, prev))
    return [(s, e) for s, e in out if e > s]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--tz-offset-h", type=float, default=0.0)
    ap.add_argument("--max-gap-min", type=float, default=15.0)
    a = ap.parse_args()
    per = [sessions(p, a.max_gap_min * 60) for p in a.files]
    first = min(s for ss in per for s, _ in ss)
    tz = a.tz_offset_h * 3600
    origin = (first + tz) // DAY * DAY - tz  # local midnight of the first day
    w = csv.writer(sys.stdout)
    w.writerow(["user_id", "start_s", "end_s"])
    for uid, ss in enumerate(per):
        for s, e in ss:
            w.writerow([uid, s - origin, e - origin])
    days = (max(e for ss in per for _, e in ss) - origin) / DAY
    print(f"{len(per)} users, {sum(map(len, per))} sessions, {days:.1f} days "
          f"(the simulator needs >= history_days + 2 = 9)", file=sys.stderr)


if __name__ == "__main__":
    main()
