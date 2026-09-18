#!/bin/sh
# 未配線 0 になるまでパス数を変えて再試行する。 sh tools/until_clean.sh c
cd "$(dirname "$0")/.."
kind=$1
for passes in 20 23 17 26 21; do
  sh tools/flow.sh "$kind" "$passes" > "fanctl_$kind/output/flow.txt" 2>&1
  n=$(grep -o "unconnected_items: [0-9]*" "fanctl_$kind/output/flow.txt" | head -1 | grep -o "[0-9]*$")
  echo "$kind passes=$passes unconnected=$n"
  if [ "$n" = "0" ]; then
    cp "fanctl_$kind/fanctl_$kind.kicad_pcb" "fanctl_$kind/output/clean.kicad_pcb"
    exit 0
  fi
done
exit 1
