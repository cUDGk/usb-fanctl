"""JLCPCB 発注用ファイル (Gerber ZIP / BOM / CPL) を order/<variant>/ に出す。

    python tools/export_jlc.py c
BOM の LCSC 番号は circuit.py の各部品の lcsc フィールドが唯一の出典。
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
import zipfile
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import circuit  # noqa: E402

KICAD_CLI = r"C:\Users\user\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"


def run(*args):
    subprocess.run([KICAD_CLI, *args], check=True, capture_output=True)


def natural(ref: str):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def main(kind: str):
    board = ROOT / f"fanctl_{kind}" / f"fanctl_{kind}.kicad_pcb"
    out = ROOT / "order" / f"fanctl_{kind}"
    gerb = out / "gerber"
    gerb.mkdir(parents=True, exist_ok=True)
    for old in gerb.iterdir():
        old.unlink()
    run("pcb", "export", "gerbers", "--layers", LAYERS, "--no-x2", "--subtract-soldermask",
        "--use-drill-file-origin", "-o", str(gerb) + "\\", str(board))
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
        "--excellon-units", "mm", "--generate-map", "--map-format", "gerberx2",
        "-o", str(gerb) + "\\", str(board))
    zpath = out / f"fanctl_{kind}_gerber.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(gerb.iterdir()):
            z.write(f, f.name)

    pos = out / "kicad_pos.csv"
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "front",
        "--exclude-dnp", "-o", str(pos), str(board))
    with pos.open(encoding="utf-8-sig", newline="") as f:
        rows = {r["Ref"]: r for r in csv.DictReader(f)}

    comps = {c["ref"]: c for c in circuit.variant(kind).COMPONENTS}
    missing = sorted(set(comps) - set(rows), key=natural)
    if missing:
        raise SystemExit(f"position file lacks: {missing}")

    with (out / f"fanctl_{kind}_cpl.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref in sorted(comps, key=natural):
            r = rows[ref]
            w.writerow([ref, f"{r['PosX']}mm", f"{r['PosY']}mm", "Top", r["Rot"]])

    groups: OrderedDict = OrderedDict()
    for ref in sorted(comps, key=natural):
        c = comps[ref]
        key = (c["value"], c["fp"].split(":")[1], c["lcsc"])
        groups.setdefault(key, []).append(ref)
    with (out / f"fanctl_{kind}_bom.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (value, fp, lcsc), refs in groups.items():
            w.writerow([value, ",".join(refs), fp, lcsc])
    print(f"{kind}: parts={len(comps)} bom_lines={len(groups)} zip={zpath.name}")


if __name__ == "__main__":
    main(sys.argv[1])
