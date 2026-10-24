#!/data/data/com.termux/files/usr/bin/bash
# Shows whether a benchmark is running and what it has written so far.
# Safe to run from a second Termux session while 02 is running.
D=$(ls -dt ~/phonebench/*/ 2>/dev/null | head -1)
if [ -z "$D" ]; then echo "no results yet (~/phonebench is empty)"; exit 0; fi
echo "latest run: $D"
echo "--- progress"; tail -n 5 "$D/progress.txt" 2>/dev/null || echo "(old script version: no progress file)"
echo "--- files"; ls -l "$D"
echo "--- last battery sample"; tail -n 1 "$D/battery.log" 2>/dev/null | cut -c1-200
echo "--- running now"
P=$(ps -e -o pid,etime,args 2>/dev/null | grep -E 'llama-(bench|batched)' | grep -v grep)
if [ -n "$P" ]; then
  echo "YES: benchmark is running"; echo "$P" | cut -c1-120
else
  echo "NO benchmark process running"
fi
