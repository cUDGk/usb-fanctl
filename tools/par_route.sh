#!/bin/sh
# パス数違いの freerouting を同時に走らせ、出来た SES を順に取り込んで未接続 0 を探す。
#   sh tools/par_route.sh a 18 20 24 28
# 逐次リトライ (until_clean.sh) だと 1 回 5 分 x 試行回数かかるため、配線だけ並列化する。
# 取り込みと DRC は基板ファイルを共有するので必ず 1 本ずつ行う。
cd "$(dirname "$0")/.."
K="/c/Users/user/AppData/Local/Programs/KiCad/10.0/bin/python.exe"
JAVA="/c/Users/user/KiCadProjects/_tools/jdk-25.0.4.1+1-jre/bin/java.exe"
JAR="C:\\Users\\user\\KiCadProjects\\vrc-fbt\\tools\\freerouting.jar"
kind=$1
shift
out="fanctl_$kind/output"
"$K" pcb.py "$kind" > "$out/build.log" 2>&1

for p in "$@"; do
  cp "fanctl_$kind/fanctl_$kind.dsn" "$out/par_$p.dsn"
  "$JAVA" -jar "$JAR" -de "$out/par_$p.dsn" -do "$out/par_$p.ses" -mp "$p" \
    --gui.enabled=false --api_server.enabled=false > "$out/par_$p.log" 2>&1 &
done
wait

for p in "$@"; do
  [ -f "$out/par_$p.ses" ] || continue
  "$K" pcb.py "$kind" --ses "$out/par_$p.ses" > "$out/import.log" 2>&1 \
    || "$K" pcb.py "$kind" --ses "$out/par_$p.ses" > "$out/import.log" 2>&1
  python tools/drc.py "$kind" --all > "$out/drc.txt" 2>&1
  n=$(grep -o "unconnected_items: [0-9]*" "$out/drc.txt" | head -1 | grep -o "[0-9]*$")
  v=$(grep -o "', 'clearance'): [0-9]*" "$out/drc.txt" | grep -o "[0-9]*$")
  echo "passes=$p unconnected=$n clearance=${v:-0}"
  if [ "$n" = "0" ]; then
    cp "fanctl_$kind/fanctl_$kind.kicad_pcb" "$out/clean.kicad_pcb"
    exit 0
  fi
done
exit 1
