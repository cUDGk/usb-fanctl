#!/bin/sh
# 配置 → 自動配線 → 取り込み → DRC 要約。 sh tools/flow.sh c 14
set -e
cd "$(dirname "$0")/.."
K="/c/Users/user/AppData/Local/Programs/KiCad/10.0/bin/python.exe"
kind=$1
passes=${2:-14}
"$K" pcb.py "$kind" > "fanctl_$kind/output/build.log" 2>&1
grep -i "failed\|Error" "fanctl_$kind/output/build.log" || true
python tools/route.py "$kind" "$passes"
# SES 取り込みは初回に SWIG の型が崩れて失敗することがあるため 1 回だけ再試行する
"$K" pcb.py "$kind" --ses "fanctl_$kind/fanctl_$kind.ses" > "fanctl_$kind/output/import.log" 2>&1 \
  || "$K" pcb.py "$kind" --ses "fanctl_$kind/fanctl_$kind.ses" > "fanctl_$kind/output/import.log" 2>&1
python tools/drc.py "$kind" --all > "fanctl_$kind/output/drc.txt" 2>&1
grep "==" "fanctl_$kind/output/drc.txt"
grep -v "silk_\|footprint_symbol\|net_conflict\|==" "fanctl_$kind/output/drc.txt" | cut -c1-220 || true
