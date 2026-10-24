#!/data/data/com.termux/files/usr/bin/bash
# Sends live status to GitHub so it can be read remotely: every 5 minutes it
# pushes status.txt, progress and a battery-log tail to the `phone-reports`
# branch of this repo. When the run says DONE it pushes all results (serial,
# IMEI and MAC lines removed) and stops.
# One-time setup: save a GitHub token with write access to this repo:
#   echo 'github_pat_...' > ~/.nsreport_token && chmod 600 ~/.nsreport_token
# Run in a second Termux session:  bash report.sh
set -uo pipefail
TOK=$(cat ~/.nsreport_token 2>/dev/null) || { echo "missing ~/.nsreport_token (see top of this file)"; exit 1; }
URL="https://x-access-token:${TOK}@github.com/aidinb/nightshift-phone-llm.git"
R=~/.nsreports; MODEL=$(getprop ro.product.model | tr ' ' _); EVERY=${EVERY:-300}
if [ ! -d "$R/.git" ]; then
  git clone -q --branch phone-reports "$URL" "$R" 2>/dev/null || {
    git init -q "$R" && git -C "$R" checkout -q -b phone-reports && git -C "$R" remote add origin "$URL"; }
fi
git -C "$R" remote set-url origin "$URL"
git -C "$R" config user.name "nightshift-phone"; git -C "$R" config user.email "phone@nightshift.invalid"
push() {
  D=$(ls -dt ~/phonebench/*/ 2>/dev/null | head -1)
  mkdir -p "$R/$MODEL"
  { date -u '+report %Y-%m-%d %H:%M:%S UTC'; bash ~/nightshift-phone-llm/bench/status.sh; } > "$R/$MODEL/status.txt" 2>&1
  if [ -n "$D" ]; then
    cp "$D/progress.txt" "$R/$MODEL/" 2>/dev/null
    tail -n 300 "$D/battery.log" > "$R/$MODEL/battery_tail.log" 2>/dev/null
  fi
  if [ "${1:-}" = final ]; then
    T=$(mktemp -d); cp -r ~/phonebench "$T/"
    find "$T" -name getprop.txt -exec sed -i -E '/serial|imei|ro\.boot\.(serialno|ap_serial)|bt\.address|wifi.*mac/Id' {} +
    tar -czf "$R/$MODEL/phonebench_$(date +%Y%m%d_%H%M).tar.gz" -C "$T" phonebench; rm -rf "$T"
  fi
  git -C "$R" add -A && git -C "$R" commit -qm "report $(date -u +%H:%M)" 2>/dev/null
  git -C "$R" push -q -u origin phone-reports 2>&1 | sed "s/${TOK}/***/g" | tail -2 && echo "$(date +%H:%M) report sent"
}
while true; do
  push
  D=$(ls -dt ~/phonebench/*/ 2>/dev/null | head -1)
  if [ -n "$D" ] && grep -q DONE "$D/progress.txt" 2>/dev/null; then push final; echo "final results sent"; exit 0; fi
  sleep "$EVERY"
done
