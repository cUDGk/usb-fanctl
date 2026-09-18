"""基板を PDF 経由で PNG 化して目視確認する。python tools/snap.py c [layers] [clip x0,y0,x1,y1]"""

import subprocess
import sys
from pathlib import Path

import fitz

KICAD_CLI = r"C:\Users\user\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"
root = Path(__file__).resolve().parents[1]
kind = sys.argv[1]
layers = sys.argv[2] if len(sys.argv) > 2 else "F.Cu,F.SilkS,F.Fab,Edge.Cuts"
board = root / f"fanctl_{kind}" / f"fanctl_{kind}.kicad_pcb"
out_dir = root / f"fanctl_{kind}" / "output"
out_dir.mkdir(exist_ok=True)
tag = layers.replace(",", "_").replace(".", "")
pdf = out_dir / f"snap_{tag}.pdf"
subprocess.run(
    [KICAD_CLI, "pcb", "export", "pdf", "--layers", layers, "--mode-single", "--include-border-title",
     "-o", str(pdf), str(board)],
    check=True, capture_output=True,
)
page = fitz.open(pdf)[0]
# 基板座標 (mm) → PDF 座標 (pt)。A4 横ページ上で KiCad は 1mm = 72/25.4pt でそのまま配置する
k = 72 / 25.4
x0, y0, x1, y1 = (float(v) for v in (sys.argv[3].split(",") if len(sys.argv) > 3 else (98, 98, 180, 132)))
clip = fitz.Rect(x0 * k, y0 * k, x1 * k, y1 * k)
png = out_dir / f"snap_{tag}.png"
page.get_pixmap(dpi=int(sys.argv[4]) if len(sys.argv) > 4 else 600, clip=clip).save(png)
print(png)
