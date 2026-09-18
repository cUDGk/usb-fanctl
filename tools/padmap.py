"""配置済み基板の主要部品のパッド座標とネットを表示する (配線計画用)。"""
import sys
import pcbnew
board = pcbnew.LoadBoard(sys.argv[1])
refs = sys.argv[2].split(",")
for ref in refs:
    fp = board.FindFootprintByReference(ref)
    for pad in sorted(fp.Pads(), key=lambda p: p.GetNumber()):
        pos = pad.GetPosition(); size = pad.GetBoundingBox()
        print(f"{ref}.{pad.GetNumber():4} ({pcbnew.ToMM(pos.x):8.3f},{pcbnew.ToMM(pos.y):8.3f}) "
              f"bbox {pcbnew.ToMM(size.GetWidth()):.2f}x{pcbnew.ToMM(size.GetHeight()):.2f} {pad.GetNetname()}")
