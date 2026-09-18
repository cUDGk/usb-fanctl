"""配置計画用: 回路の各フットプリントのコートヤード寸法を表示する (KiCad 同梱 Python で実行)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pcbnew  # noqa: E402
from pcbgen import load_footprint  # noqa: E402
import circuit  # noqa: E402

seen = {}
for comp in circuit.variant(sys.argv[1] if len(sys.argv) > 1 else "c").COMPONENTS:
    seen.setdefault(comp["fp"], []).append(comp["ref"])
for fp, refs in seen.items():
    f = load_footprint(fp)
    box = f.GetCourtyard(pcbnew.F_CrtYd).BBox() if f.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() else f.GetBoundingBox(False)
    w, h = pcbnew.ToMM(box.GetWidth()), pcbnew.ToMM(box.GetHeight())
    cx, cy = pcbnew.ToMM(box.GetCenter().x), pcbnew.ToMM(box.GetCenter().y)
    print(f"{w:6.2f} x {h:6.2f}  c=({cx:5.2f},{cy:5.2f})  {fp.split(':')[1][:45]:45} {' '.join(refs)}")
