#!/data/data/com.termux/files/usr/bin/bash
# Packs ~/phonebench into one file in the phone's Download folder, so you can
# attach it in the Claude app (or send it to yourself). Strips the serial number.
set -euo pipefail
[ -d ~/storage/downloads ] || termux-setup-storage
sleep 2
for f in ~/phonebench/*/getprop.txt; do
  [ -f "$f" ] && sed -i -E '/serial|imei|ro\.boot\.(serialno|ap_serial)|bt\.address|wifi.*mac/Id' "$f"
done
NAME=phonebench_$(getprop ro.product.model | tr ' ' _)_$(date +%Y%m%d_%H%M).tar.gz
tar -czf ~/storage/downloads/"$NAME" -C ~ phonebench
ls -lh ~/storage/downloads/"$NAME"
echo "Saved to the phone's Download folder as $NAME. Attach it in the Claude app."
