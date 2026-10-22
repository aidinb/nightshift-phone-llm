#!/data/data/com.termux/files/usr/bin/bash
# Logs charging, Wi-Fi and screen state every 5 minutes for the availability
# trace. Volunteers run this for 14 days; nothing else is recorded.
# Install once:  termux-job-scheduler --job-id 7 --period-ms 300000 --persisted true \
#                  --script ~/bench/05_availability_logger.sh
LOG=~/phonebench/availability.csv
mkdir -p ~/phonebench
[ -f "$LOG" ] || echo "ts,plugged,wifi_ssid_present,battery_pct" > "$LOG"
b=$(termux-battery-status)
plugged=$(echo "$b" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(int(d["plugged"]!="UNPLUGGED"))')
pct=$(echo "$b" | python3 -c 'import json,sys; print(json.load(sys.stdin)["percentage"])')
w=$(termux-wifi-connectioninfo | python3 -c 'import json,sys; d=json.load(sys.stdin); print(int(d.get("supplicant_state")=="COMPLETED"))')
echo "$(date +%s),$plugged,$w,$pct" >> "$LOG"
