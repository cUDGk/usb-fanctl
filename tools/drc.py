"""kicad-cli の DRC を回して要約する。python tools/drc.py c [--all]"""

import collections
import json
import subprocess
import sys
from pathlib import Path

KICAD_CLI = r"C:\Users\user\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"
root = Path(__file__).resolve().parents[1]
kind = sys.argv[1]
board = root / f"fanctl_{kind}" / f"fanctl_{kind}.kicad_pcb"
out = root / f"fanctl_{kind}" / "output" / "drc.json"
out.parent.mkdir(exist_ok=True)
subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--schematic-parity", "--refill-zones",
                "--save-board", "-o", str(out), str(board)], capture_output=True)
d = json.loads(out.read_text(encoding="utf-8"))
sys.stdout.reconfigure(encoding="utf-8")
for key in ("violations", "unconnected_items", "schematic_parity"):
    items = d.get(key, [])
    c = collections.Counter((v["severity"], v["type"]) for v in items)
    print(f"== {key}: {len(items)}", dict(c))
    shown = collections.Counter()
    for v in items:
        k = v["type"]
        if shown[k] >= (1000 if "--all" in sys.argv else 6):
            continue
        shown[k] += 1
        print("  ", k, "|", v["description"], "|", " ; ".join(
            f"{i['description']} @({i['pos']['x']:.2f},{i['pos']['y']:.2f})" for i in v["items"]))
