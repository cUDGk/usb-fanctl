"""指定ネット (主に GND) の表面実装パッドの脇に、内層プレーンへ落とすビアを自動配置する。

freerouting はプレーンへのファンアウトを確実にはやらないため、配線前に
「パッド → 短配線 → ビア」を決め打ちで置き、自動配線からはそのネットを外す。
障害物判定はパッドを外接矩形、配線を線分、ポリゴンを多角形として保守的に行う。
"""

from __future__ import annotations

import math

import pcbnew

VIA_R = 0.25  # 0.5mm 径 (穴 0.3mm)
CLEAR = 0.16  # 製造下限 0.1 (4 層) に対し余裕を持つ
STUB_W = 0.3


def _mm(v):
    return pcbnew.ToMM(v)


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def _box_dist(p, box):
    x0, y0, x1, y1 = box
    dx = max(x0 - p[0], 0.0, p[0] - x1)
    dy = max(y0 - p[1], 0.0, p[1] - y1)
    return math.hypot(dx, dy)


def _seg_box_dist(a, b, box, steps=12):
    return min(_box_dist((a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps), box)
               for i in range(steps + 1))


def _in_poly(p, poly):
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _poly_dist(p, poly):
    if _in_poly(p, poly):
        return 0.0
    return min(_seg_dist(p, a, b) for a, b in zip(poly, poly[1:] + poly[:1]))


class _World:
    def __init__(self, board, zones, bounds):
        self.pads = []  # (box, net)
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                bb = pad.GetBoundingBox()
                box = (_mm(bb.GetX()), _mm(bb.GetY()), _mm(bb.GetRight()), _mm(bb.GetBottom()))
                through = pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
                on_top = pad.IsOnLayer(pcbnew.F_Cu)
                self.pads.append((box, pad.GetNetname(), on_top, through))
        self.tracks = []  # (a, b, half_width, net, layer)
        self.vias = []  # (center, radius, net)
        for item in board.GetTracks():
            if isinstance(item, pcbnew.PCB_VIA):
                pos = item.GetPosition()
                self.vias.append(((_mm(pos.x), _mm(pos.y)), VIA_R, item.GetNetname()))
            else:
                s, e = item.GetStart(), item.GetEnd()
                self.tracks.append(((_mm(s.x), _mm(s.y)), (_mm(e.x), _mm(e.y)),
                                    _mm(item.GetWidth()) / 2, item.GetNetname(), item.GetLayer()))
        self.zones = zones  # (net, layer_name, points)
        self.bounds = bounds

    def via_ok(self, c, net):
        x0, y0, x1, y1 = self.bounds
        if not (x0 + 0.6 <= c[0] <= x1 - 0.6 and y0 + 0.6 <= c[1] <= y1 - 0.6):
            return False
        need = VIA_R + CLEAR
        for box, pnet, _, through in self.pads:
            if (pnet != net or through or not pnet) and _box_dist(c, box) < need + (0.1 if through else 0):
                return False
        for a, b, hw, tnet, _ in self.tracks:
            if tnet != net and _seg_dist(c, a, b) < need + hw:
                return False
        for vc, vr, vnet in self.vias:
            gap = CLEAR if vnet != net else 0.25  # 同ネットでも穴同士は離す
            if math.hypot(c[0] - vc[0], c[1] - vc[1]) < VIA_R + vr + gap:
                return False
        for znet, layer, pts in self.zones:
            if znet != net and layer.upper() in ("F", "B") and _poly_dist(c, pts) < need:
                return False
        return True

    def stub_ok(self, a, b, net, own_box):
        need = STUB_W / 2 + CLEAR
        for box, pnet, on_top, _ in self.pads:
            if box == own_box or not on_top:
                continue
            if pnet != net and _seg_box_dist(a, b, box) < need:
                return False
        for ta, tb, hw, tnet, layer in self.tracks:
            if tnet != net and layer == pcbnew.F_Cu:
                for i in range(13):
                    p = (a[0] + (b[0] - a[0]) * i / 12, a[1] + (b[1] - a[1]) * i / 12)
                    if _seg_dist(p, ta, tb) < need + hw:
                        return False
        for vc, vr, vnet in self.vias:
            if vnet != net and _seg_dist(vc, a, b) < need + vr:
                return False
        for znet, layer, pts in self.zones:
            if znet != net and layer.upper() == "F":
                for i in range(13):
                    p = (a[0] + (b[0] - a[0]) * i / 12, a[1] + (b[1] - a[1]) * i / 12)
                    if _poly_dist(p, pts) < need:
                        return False
        return True


def place(board, nets, zones, bounds, net_objs, extra_pad_vias=None, skip=()):
    """nets に属する表層パッドごとにビアを 1 本 (既存の近いビアがあれば共用) 置く。

    extra_pad_vias: {(ref, pad): [(dx, dy), ...]} 露出パッド内に打つビアの相対座標。
    戻り値: 配置できなかったパッドの一覧。
    """
    world = _World(board, zones, bounds)
    failed = []
    extra_pad_vias = extra_pad_vias or {}
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        ref = fp.GetReference()
        for pad in fp.Pads():
            net = pad.GetNetname()
            if net not in nets or (ref, pad.GetNumber()) in skip:
                continue
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                continue  # 貫通パッドは全層で繋がる
            pos = pad.GetPosition()
            c = (_mm(pos.x), _mm(pos.y))
            bb = pad.GetBoundingBox()
            box = (_mm(bb.GetX()), _mm(bb.GetY()), _mm(bb.GetRight()), _mm(bb.GetBottom()))
            key = (ref, pad.GetNumber())
            if key in extra_pad_vias:
                for dx, dy in extra_pad_vias[key]:
                    _add_via(board, world, (c[0] + dx, c[1] + dy), net_objs[net])
                continue
            # 既存の同ネットビアが十分近く、途中が空いていれば共用する
            reuse = None
            for vc, _, vnet in world.vias:
                if vnet == net and _box_dist(vc, box) < 1.0 and world.stub_ok(c, vc, net, box):
                    reuse = vc
                    break
            if reuse:
                _add_track(board, world, c, reuse, net_objs[net])
                continue
            hw, hh = (box[2] - box[0]) / 2, (box[3] - box[1]) / 2
            best = None
            for extra in (0.55, 0.75, 1.0, 1.3, 1.7, 2.2):
                for k in range(16):
                    ang = 2 * math.pi * k / 16
                    ux, uy = math.cos(ang), math.sin(ang)
                    # 矩形の縁までの距離 + 余白
                    t = min(hw / abs(ux) if abs(ux) > 1e-9 else 1e9, hh / abs(uy) if abs(uy) > 1e-9 else 1e9)
                    v = (round(c[0] + ux * (t + extra), 3), round(c[1] + uy * (t + extra), 3))
                    if world.via_ok(v, net) and world.stub_ok(c, v, net, box):
                        best = v
                        break
                if best:
                    break
            if best is None:
                failed.append(key)
                continue
            _add_track(board, world, c, best, net_objs[net])
            _add_via(board, world, best, net_objs[net])
    return failed


def _add_track(board, world, a, b, net):
    t = pcbnew.PCB_TRACK(board)
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(net)
    t.SetWidth(pcbnew.FromMM(STUB_W))
    t.SetStart(pcbnew.VECTOR2I_MM(*a))
    t.SetEnd(pcbnew.VECTOR2I_MM(*b))
    t.SetLocked(True)
    board.Add(t)
    world.tracks.append((a, b, STUB_W / 2, net.GetNetname(), pcbnew.F_Cu))


def _add_via(board, world, c, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I_MM(*c))
    v.SetWidth(pcbnew.FromMM(2 * VIA_R))
    v.SetDrill(pcbnew.FromMM(0.3))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(net)
    v.SetLocked(True)
    board.Add(v)
    world.vias.append((c, VIA_R, net.GetNetname()))
