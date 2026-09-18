"""USB ファンコントローラ基板の配置・電源ポリゴン・手配線 (KiCad 同梱 Python で実行)。

    python.exe pcb.py c            # 配置して DSN を出す
    python.exe pcb.py c --ses X    # freerouting の結果を取り込み、ポリゴンを流して保存

4 層: F=部品+信号 / In1=GND ベタ / In2=電源分割プレーン / B=信号+GND。
大電流ネット (VBUS_*, VSYS, VOUT_RAW, +12V, SW1, SW2) は自動配線に渡さず、
表層ポリゴン + In2 プレーン + ビアで手配置する。細い信号と GND は freerouting が引く。
座標系: 基板左上 (100,100)、右へ +x、下へ +y。PC 側プラグは左端、PD 入力とファンは右端。
"""

from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pcbnew  # noqa: E402

import circuit  # noqa: E402
from pcbgen import BoardConfig, Placement, build_board, import_and_finish, load_footprint  # noqa: E402

P = Placement
X0, Y0, W, H = 100.0, 100.0, 90.0, 34.0
X1, Y1 = X0 + W, Y0 + H
POWER_NETS = {"VBUS_PC", "VBUS_EXT", "VSYS", "VOUT_RAW", "+12V", "SW1", "SW2"}
# GND も自動配線から外し、パッド脇の自動ビアで In1 に落とす
# 完全に手配線したネットも自動配線から外す。銅箔は DSN に残るので障害物としては効く。
# (長い手配線を入れると freerouting がパス途中でハングするため、対象から外すのが確実)
HAND_ROUTED = {"ADC_IOUT", "ADC_ILM_EXT", "EXT_OVLO", "QSPI_SD2"}
UNROUTED = POWER_NETS | {"GND"} | HAND_ROUTED

# --- 配置 ------------------------------------------------------------------
COMMON = {
    # PC 側 USB (J1・USBLC6・CC/分圧抵抗はバリアント側)
    "C1": P(110.9, 121.2, 180),
    "U3": P(113.0, 124.5),
    "R7": P(110.4, 123.4, 180),
    "R10": P(110.4, 124.5),
    "R11": P(110.4, 125.6, 180),
    "R6": P(116.3, 124.2),
    "R12": P(116.3, 125.3),
    "C2": P(116.3, 126.4),
    "U8": P(117.0, 104.2, 270),
    "C43": P(114.4, 104.2, 270),
    "C44": P(120.4, 105.6),
    "C40": P(121.2, 107.4),
    # MCU (180°: GPIO は右 = 電源段側、USB/VREG/QSPI は下、水晶は上)
    "U6": P(130.0, 115.0, 180),
    "Y1": P(135.5, 107.8, 180),
    "R38": P(132.4, 109.3),
    "C28": P(137.8, 105.4),
    "C29": P(135.2, 110.1),
    "C34": P(127.0, 109.3, 180),
    "C36": P(127.0, 110.4, 180),
    "C33": P(124.3, 114.0, 180),
    "C38": P(124.8, 118.9, 180),
    "C35": P(124.8, 120.1, 180),
    "C41": P(124.8, 121.3, 180),
    "C39": P(127.3, 120.9, 180),
    "C31": P(129.6, 121.8, 270),
    "C37": P(130.7, 123.6, 270),
    "C30": P(135.4, 118.5),
    "C32": P(135.4, 119.55),
    "U7": P(136.2, 126.2, 90),
    "C42": P(132.2, 124.9, 180),
    "R40": P(131.6, 128.6),
    "SW1": P(126.0, 129.4),
    "D3": P(141.0, 102.0),
    "R41": P(138.0, 102.0),
    # プルアップ/プルダウン類は上辺に一列 (MCU と電源段の間の配線路を空ける)
    "R42": P(139.8, 104.5, 270),
    "R43": P(140.8, 104.5, 270),
    "R33": P(141.8, 104.5, 270),
    "R32": P(151.0, 103.5, 90),
    "R8": P(143.8, 104.5, 270),
    "R15": P(144.8, 104.5, 270),
    "R16": P(145.8, 104.5, 270),
    "R22": P(146.8, 104.5, 270),
    "R9": P(147.8, 104.5, 270),
    "R36": P(148.8, 104.5, 270),
    "R37": P(149.8, 104.5, 90),
    # 昇降圧
    "U1": P(157.0, 117.0),
    "L1": P(156.5, 109.2),
    "Q2": P(149.5, 108.8, 270),
    "Q1": P(150.0, 115.2, 180),
    "C8": P(156.3, 113.4, 180),
    "C9": P(158.5, 113.4),
    "R24": P(147.4, 114.2, 90),
    "R25": P(146.9, 111.0, 90),
    "C10": P(142.8, 114.5, 90),
    "C11": P(145.2, 114.5, 90),
    "C12": P(153.0, 115.6, 90),
    "C13": P(145.4, 127.0, 270),
    "C14": P(160.0, 120.4),
    "C15": P(160.0, 122.8),
    "C16": P(160.0, 125.2),
    "C17": P(160.0, 127.6),
    "C18": P(156.1, 122.2, 180),
    "C19": P(153.3, 128.5, 270),
    "C20": P(160.6, 130.7, 270),
    "R26": P(158.4, 131.5, 270),
    "C21": P(160.9, 114.6),
    "R29": P(162.1, 116.0),
    "C23": P(164.0, 116.0),
    "C24": P(164.0, 117.2),
    "R28": P(162.1, 117.2),
    "R30": P(162.1, 118.4),
    "R31": P(164.0, 118.4),
    "C25": P(166.2, 118.4),
    "C22": P(154.2, 119.8),
    "R27": P(155.87, 120.1, 270),
    # PD 入力
    "J2": P(186.65, 112.0, 90),
    "U2": P(178.0, 112.0, 180),
    "D1": P(181.5, 102.3),
    "C3": P(185.5, 118.8),
    "D4": P(176.8, 106.8),
    "U4": P(170.5, 106.0),
    "C4": P(166.9, 107.6, 180),
    "C5": P(166.9, 104.6, 180),
    "C6": P(166.9, 103.4, 180),
    "R13": P(172.2, 102.2),
    "R14": P(172.9, 108.6),
    "R17": P(180.5, 117.8),
    "R18": P(180.5, 118.9),
    "R19": P(180.5, 120.0),
    "C7": P(174.8, 111.1, 180),
    "R21": P(174.8, 112.6, 180),
    "R23": P(173.0, 114.2, 90),
    # ファン
    "J3": P(173.0, 130.0),
    "Q3": P(171.5, 124.2, 90),
    "R34": P(167.2, 123.8, 90),
    "R35": P(168.3, 123.8, 90),
    "D2": P(186.0, 126.8),
    "C26": P(183.0, 123.2, 270),
    "C27": P(185.0, 123.2, 270),
}

VARIANT = {
    "c": {
        # 基板端マーカー (ローカル y=3.47) を x=100 に合わせ、本体を左へ出す
        "J1": P(103.47, 117.0, 270),
        # USBLC6 は 1→6 (D-) が上、3→4 (D+) が下のフロースルー
        "U5": P(111.4, 116.3),
        "R5": P(114.8, 115.35),
        "R4": P(114.8, 117.25),
        "R1": P(107.6, 122.6, 270),
        "R2": P(108.8, 123.2, 270),
    },
    "a": {
        # 右アングル THT プラグ。本体は +y 方向なので 270° 回して左へ出す (基板端 = ローカル y 2.8)
        "J1": P(102.8, 117.0, 270),
        # A プラグは D+ が上。USBLC6 を 180° 回し 4→3 (D+) を上、6→1 (D-) を下にする
        "U5": P(111.4, 117.0, 180),
        "R4": P(114.8, 116.05),
        "R5": P(114.8, 117.95),
        "R1": P(116.4, 112.4),
        "R2": P(116.4, 111.3),
    },
}


@lru_cache(maxsize=None)
def _footprint(fp_id: str):
    return load_footprint(fp_id)


class Layout:
    """配置から絶対座標を引き、ポリゴン・ビア・短配線の設定を組み立てる。"""

    def __init__(self, placements, components):
        self.placements = placements
        self.fps = {c["ref"]: c["fp"] for c in components}
        self.zones: list = []
        self.keepouts: list = []
        self.routes: list = []
        self.vias: list = []

    def pad(self, ref: str, number: str) -> tuple[float, float]:
        fp = _footprint(self.fps[ref])
        pl = self.placements[ref]
        fp.SetOrientationDegrees(pl.rotation)
        fp.SetPosition(pcbnew.VECTOR2I_MM(pl.x, pl.y))
        hits = [p for p in fp.Pads() if p.GetNumber() == number]
        if not hits:
            raise KeyError(f"{ref}.{number}")
        pos = hits[0].GetPosition()
        return round(pcbnew.ToMM(pos.x), 4), round(pcbnew.ToMM(pos.y), 4)

    def pour(self, net, points, layer="F", priority=2, keepout=True):
        self.zones.append((net, layer, points, priority))
        if keepout and layer in ("F", "B"):
            self.keepouts.append((layer, points))

    def via_array(self, net, xs, ys):
        for x in xs:
            for y in ys:
                self.vias.append((net, x, y))

    def stub(self, net, ref, number, *path, width=0.3, via=True):
        """パッドから path を通る短配線を引き、終点にビアを置く (プレーンへの落とし込み)。"""
        start = self.pad(ref, number)
        pts = [start, *path]
        self.routes.append((net, "F", width, pts))
        if via:
            self.vias.append((net, *pts[-1]))


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _power_stage(L: Layout):
    # SW1: Q1 ソース行 + Q2 ドレイン + L1 パッド1 + U1 SW1 ピン
    L.pour("SW1", [(148.75, 106.8), (155.2, 106.8), (155.2, 110.6), (156.36, 110.6), (156.36, 115.7),
                   (155.55, 115.7), (155.55, 114.15), (149.35, 114.15), (149.35, 113.2), (148.75, 113.2)])
    # SW2: L1 パッド2 + C9 + U1 SW2 ピン
    L.pour("SW2", [(157.2, 106.8), (161.3, 106.8), (161.3, 112.8), (159.45, 112.8), (159.45, 114.0),
                   (158.6, 114.0), (158.6, 112.8), (157.6, 112.8), (157.6, 115.7), (157.2, 115.7)])
    # VSYS: Q1 ドレイン + 入力コンデンサ + U1 VIN ピンへの細い帯
    L.pour("VSYS", [(142.8, 114.35), (146.7, 114.35), (146.7, 115.0), (148.1, 115.0), (148.1, 114.35), (151.6, 114.35), (151.6, 116.3), (155.05, 116.3), (155.05, 116.7),
                    (151.6, 116.7), (151.6, 117.1), (148.0, 117.1), (148.0, 118.4), (142.8, 118.4)])
    L.via_array("VSYS", [143.4, 144.2, 145.0, 145.8, 146.6, 147.4], [117.0, 117.8])
    # VOUT_RAW: U1 VOUT/ISP から下へ伸びる帯。右に出力 MLCC、左に 1uF とハイブリッド電解、下端に R26
    L.pour("VOUT_RAW", [(157.35, 118.35), (158.25, 118.35), (158.25, 119.2), (158.75, 119.2),
                        (158.75, 129.3), (158.95, 129.3), (158.95, 130.7), (157.05, 130.7),
                        (157.05, 125.6), (152.6, 125.6), (152.6, 124.4), (157.05, 124.4), (157.05, 119.2), (157.35, 119.2)])
    # +12V: R26 の出側。In2 の +12V プレーンへ落とす
    L.pour("+12V", rect(156.9, 131.75, 161.4, 133.5))
    L.via_array("+12V", [159.9, 160.8], [132.6])
    # ISN はケルビン接続: U1 → ビア → 裏面 → C20/R26 出側
    isn_via, isn_end = (159.55, 119.35), (161.6, 131.4)
    L.routes.append(("+12V", "F", 0.25, [L.pad("U1", "13"), isn_via]))
    L.routes.append(("+12V", "B", 0.25, [isn_via, (162.4, 121.0), (162.4, 130.0), isn_end]))
    L.vias += [("+12V", *isn_via), ("+12V", *isn_end)]
    L.routes.append(("+12V", "F", 0.25, [isn_end, L.pad("C20", "2")]))
    L.routes.append(("VOUT_RAW", "F", 0.3, [L.pad("C20", "1"), (158.9, 130.2)]))
    # U1 の PGND 帯と PGND ピンを直結、TESTEN は露出パッドへ
    L.routes.append(("GND", "F", 0.3, [L.pad("U1", "24"), L.pad("U1", "9")]))
    # 中央の SW2/VOUT 帯を上下のピンへ (パッケージ内でも同電位だが電流を分担させる)
    L.routes.append(("VOUT_RAW", "F", 0.25, [(157.6, 117.6), (157.6, 118.5)]))
    L.routes.append(("SW2", "F", 0.25, [(157.15, 116.4), (157.15, 115.5)]))
    L.routes.append(("BB_FSW", "F", 0.25, [L.pad("U1", "8"), L.pad("R27", "1")]))
    # CDC は周辺抵抗の列を避けて裏面経由で R30 へ
    cdc_a, cdc_b = (159.6, 117.0), (160.85, 119.05)
    L.routes.append(("BB_CDC", "F", 0.2, [L.pad("U1", "16"), cdc_a]))
    L.routes.append(("BB_CDC", "B", 0.2, [cdc_a, (160.85, 117.0), cdc_b]))
    L.routes.append(("BB_CDC", "F", 0.2, [cdc_b, L.pad("R30", "1")]))
    L.vias += [("BB_CDC", *cdc_a), ("BB_CDC", *cdc_b)]
    L.routes.append(("GND", "F", 0.2, [L.pad("U1", "15"), (160.3, 117.5)]))
    L.routes.append(("BB_ILIM", "F", 0.2, [L.pad("U1", "17"), (160.9, 116.5), L.pad("R28", "1")]))
    L.routes.append(("BB_INT", "F", 0.2, [L.pad("U1", "14"), (159.6, 118.0), (159.75, 118.25)]))
    # BB_EN (MCU GPIO4 → U1 EN) は電源段の下を裏面で一直線に渡す
    en_a, en_b = (135.2, 115.6), (153.3, 117.4)
    L.routes.append(("BB_EN", "F", 0.2, [L.pad("U6", "6"), en_a]))
    L.routes.append(("BB_EN", "B", 0.2, [en_a, (152.8, 115.6), en_b]))
    L.routes.append(("BB_EN", "F", 0.2, [en_b, (154.8, 117.0), L.pad("U1", "4")]))
    L.vias += [("BB_EN", *en_a), ("BB_EN", *en_b)]
    # SCL/SDA は U1 左列で BB_EN に挟まれて抜けられない。C12 下の空きチャネルを 0.6mm ピッチで
    # 平行に走らせ、ビアの位置を x 方向にずらして裏面へ渡す
    L.routes.append(("I2C_SCL", "F", 0.2, [L.pad("U1", "5"), (154.5, 117.5), (153.8, 117.95), (152.2, 117.95)]))
    L.vias.append(("I2C_SCL", 152.2, 117.95))
    # SCL の逃げ (y=117.5 → 117.95) と広がる向きに曲げる。U1 の角パッド (pad 7) には y=118.2 より上で近づかない
    L.routes.append(("I2C_SDA", "F", 0.2, [L.pad("U1", "6"), (154.6, 118.0), (153.8, 118.9), (151.6, 119.4), (151.0, 119.4)]))
    L.vias.append(("I2C_SDA", 151.0, 119.4))
    L.routes.append(("GND", "F", 0.3, [L.pad("C12", "2"), (152.05, 114.75)]))
    L.vias.append(("GND", 152.05, 114.75))
    L.vias.append(("BB_INT", 159.75, 118.25))
    L.vias.append(("GND", 160.3, 117.5))
    # BOOT コンデンサ
    L.routes.append(("BOOT1", "F", 0.25, [L.pad("C8", "1"), (156.75, 114.6), L.pad("U1", "22")]))
    L.routes.append(("BOOT2", "F", 0.25, [L.pad("C9", "1"), (158.05, 114.6), L.pad("U1", "20")]))
    # ゲート駆動: U1 → ビア → 裏面 → ビア → ゲート抵抗 → ゲート
    dr1l_via, dr1h_via = (154.1, 114.55), (153.95, 116.0)
    L.routes.append(("BB_LDRV", "F", 0.3, [L.pad("U1", "1"), dr1l_via]))
    L.routes.append(("BB_HDRV", "F", 0.3, [L.pad("U1", "2"), dr1h_via]))
    ldrv_near, hdrv_near = (146.0, 111.5), (146.6, 113.1)
    L.routes.append(("BB_LDRV", "B", 0.3, [dr1l_via, (152.6, 112.4), (148.2, 112.4), ldrv_near]))
    L.routes.append(("BB_HDRV", "B", 0.3, [dr1h_via, (152.4, 113.6), (147.6, 113.6), hdrv_near]))
    L.vias += [("BB_LDRV", *dr1l_via), ("BB_HDRV", *dr1h_via), ("BB_LDRV", *ldrv_near), ("BB_HDRV", *hdrv_near)]
    L.routes.append(("BB_LDRV", "F", 0.3, [ldrv_near, L.pad("R25", "1")]))
    L.routes.append(("BB_HDRV", "F", 0.3, [hdrv_near, (146.6, 114.71), L.pad("R24", "1")]))
    L.routes.append(("BB_LG", "F", 0.3, [L.pad("R25", "2"), L.pad("Q2", "4")]))
    L.routes.append(("BB_HG", "F", 0.3, [L.pad("R24", "2"), L.pad("Q1", "4")]))
    # 部品の小パッドを In2 プレーンへ
    L.stub("VSYS", "C13", "1", (145.4, 124.3))
    L.vias += [("VSYS", 144.6, 124.3), ("VSYS", 146.2, 124.3)]
    L.routes.append(("VSYS", "F", 0.6, [(144.6, 124.3), (146.2, 124.3)]))
    L.stub("+12V", "C26", "1", (183.0, 121.2))
    L.stub("+12V", "C27", "1", (185.0, 121.2))
    L.stub("+12V", "D2", "1", (184.4, 125.3))
    L.routes.append(("GND", "F", 0.25, [L.pad("U6", "19"), (131.0, 113.6)]))
    L.routes.append(("+3V3", "F", 0.25, [L.pad("C30", "1"), L.pad("C32", "1")]))
    # QSPI の上段 3 本 (SD3/SCLK/SD0) は入れ子で決め打ち。右ほど高い位置で曲げて交差を避ける
    for net, mcu_pin, flash_pin, y in (("QSPI_SD3", "51", "7", 121.05), ("QSPI_SCLK", "52", "6", 120.6),
                                       ("QSPI_SD0", "53", "5", 120.15)):
        mx, my = L.pad("U6", mcu_pin)
        fx, fy = L.pad("U7", flash_pin)
        L.routes.append((net, "F", 0.2, [(mx, my), (mx, y), (fx, y), (fx, fy)]))
    # ADC_IOUT は MCU 左側から出て基板を横断する。左の密集列の隙間でビアに落としておく
    # MCU 左側の ADC 3 本 (38:VSYS / 39:IOUT / 40:ILM_EXT) は 0.4mm ピッチで並んでいるので、
    # ビアを x 方向にずらして扇形に逃がす。38 は西へ直進できるよう通路を空けておく
    # 39 (IOUT) と 40 (ILM_EXT) はどちらも基板東端まで渡るので、2 本まとめて上辺の空き地を通す。
    # 38 (VSYS) は R1 へ北西に抜けるので y=116.0 の通路を空けたまま残す
    L.routes.append(("ADC_IOUT", "F", 0.2, [L.pad("U6", "39"), (121.4, 116.4)]))
    # 西端でも ILM のレーン (y=101.5) を跨ぐので、その区間だけ表面に上げる
    iout_h1, iout_h2 = (121.4, 102.6), (121.4, 100.9)
    L.routes.append(("ADC_IOUT", "B", 0.2, [(121.4, 116.4), iout_h1]))
    L.routes.append(("ADC_IOUT", "F", 0.2, [iout_h1, iout_h2]))
    L.routes.append(("ADC_IOUT", "B", 0.2, [iout_h2, (166.0, 100.9),
                                            (166.0, 119.8), (165.3, 119.8)]))
    L.vias += [("ADC_IOUT", *iout_h1), ("ADC_IOUT", *iout_h2)]
    L.routes.append(("ADC_IOUT", "F", 0.2, [(165.3, 119.8), L.pad("C25", "1"), L.pad("R31", "2")]))
    L.vias += [("ADC_IOUT", 121.4, 116.4), ("ADC_IOUT", 165.3, 119.8)]
    # ADC_ILM_EXT は外部 PD 側 (R23) まで基板を横断する。上辺の空き地を裏面で East へ渡す
    # ILM は IOUT (x=121.4 / y=101.5) の外側を通す。内側だと上辺で IOUT の横引きと交差する
    ilm_a, ilm_b = (120.2, 117.6), (171.5, 113.4)
    L.routes.append(("ADC_ILM_EXT", "F", 0.2, [L.pad("U6", "40"), (123.2, 116.8), (122.2, 117.6), ilm_a]))
    # IOUT の縦線 (x=166) とは表面で跨ぐ。裏面同士だと交差し、経路をずらすとルータがハングする
    ilm_h1, ilm_h2 = (165.2, 110.0), (167.3, 111.4)
    L.routes.append(("ADC_ILM_EXT", "B", 0.2, [ilm_a, (120.2, 101.5), (164.0, 101.5),
                                               (164.0, 109.0), ilm_h1]))
    L.routes.append(("ADC_ILM_EXT", "F", 0.2, [ilm_h1, ilm_h2]))
    L.routes.append(("ADC_ILM_EXT", "B", 0.2, [ilm_h2, ilm_b]))
    L.vias += [("ADC_ILM_EXT", *ilm_h1), ("ADC_ILM_EXT", *ilm_h2)]
    L.routes.append(("ADC_ILM_EXT", "F", 0.2, [ilm_b, L.pad("R23", "2")]))
    L.vias += [("ADC_ILM_EXT", *ilm_a), ("ADC_ILM_EXT", *ilm_b)]
    # QSPI_SD2 だけフラッシュの下段ピンなので、他の 3 本と違い U7 の東を回って裏面で入れる
    # ビアは SD0 の横引き (y=120.15) と SD3/SCLK/SD0 の縦引き (x<=131.4) の両方から離す
    sd2_a, sd2_b = (132.1, 119.5), (136.835, 131.6)
    L.routes.append(("QSPI_SD2", "F", 0.2, [L.pad("U6", "54"), (131.8, 118.9), sd2_a]))
    L.routes.append(("QSPI_SD2", "B", 0.2, [sd2_a, (134.0, 121.8), (136.5, 126.0), sd2_b]))
    L.routes.append(("QSPI_SD2", "F", 0.2, [sd2_b, L.pad("U7", "3")]))
    L.vias += [("QSPI_SD2", *sd2_a), ("QSPI_SD2", *sd2_b)]
    # I2C は U1・MCU・プルアップ (R42/R43) が基板の端から端に散っていて自動配線が通らないので、
    # 2 本を平行レーンとして手配線する。SCL が内側 (x=140.6 / y=118.3)、SDA が外側 (x=139.4 / y=119.9)。
    # 縦線は BB_EN の裏面配線 (y=115.6) を跨ぐ区間だけ表面に上げる
    for net, pull, xv, ych in (("I2C_SCL", "R43", 140.6, 118.3), ("I2C_SDA", "R42", 139.4, 119.9)):
        via_u1 = (152.2, 117.95) if net == "I2C_SCL" else (151.0, 119.4)
        enter = (151.8, 118.3) if net == "I2C_SCL" else (150.0, 119.9)
        top, hop_lo, hop_hi = (xv, 106.6), (xv, 117.0), (xv, 114.2)
        L.routes.append((net, "B", 0.2, [via_u1, enter, (xv, ych), hop_lo]))
        L.routes.append((net, "F", 0.2, [hop_lo, hop_hi]))
        L.routes.append((net, "B", 0.2, [hop_hi, top]))
        L.routes.append((net, "F", 0.2, [top, L.pad(pull, "2")]))
        L.vias += [(net, *hop_lo), (net, *hop_hi), (net, *top)]
    # 上辺の抵抗列に 3V3 の母線を渡す
    L.routes.append(("+3V3", "F", 0.3, [(139.8, 103.4), (148.8, 103.4)]))
    for ref in ("R42", "R43", "R33", "R8", "R15", "R16", "R22", "R9", "R36"):
        x = L.placements[ref].x
        L.routes.append(("+3V3", "F", 0.25, [(x, 103.4), L.pad(ref, "1")]))


def _pd_input(L: Layout):
    # J2 の VBUS 端子 (上下 2 組) を各 2 本のビアで In2 へ
    top_vbus, bot_vbus = L.pad("J2", "A9"), L.pad("J2", "A4")
    L.pour("VBUS_EXT", [(179.4, 108.9), (181.95, 108.9), (181.95, 109.25), (183.3, 109.25),
                        (183.3, 109.85), (181.6, 109.85), (181.6, 109.9), (179.4, 109.9)], keepout=True)
    L.pour("VBUS_EXT", [(179.4, 113.8), (181.6, 113.8), (181.6, 114.15), (183.3, 114.15),
                        (183.3, 114.75), (181.95, 114.75), (181.95, 115.1), (179.4, 115.1)], keepout=True)
    L.via_array("VBUS_EXT", [179.9, 180.7], [109.55, 114.45])
    # U2 (180° 回転): IN 帯 x≈178.23 は右、OUT 帯 x≈177.74 は左。帯の上下端から引き出す
    L.pour("VBUS_EXT", [(178.08, 111.0), (178.41, 111.0), (178.41, 110.6), (179.35, 110.6),
                        (179.35, 108.9), (178.08, 108.9)])
    L.pour("VBUS_EXT", [(178.08, 113.0), (178.41, 113.0), (178.41, 113.4), (179.35, 113.4),
                        (179.35, 115.1), (178.08, 115.1)])
    L.pour("VSYS", [(177.89, 111.0), (177.59, 111.0), (177.59, 110.6), (175.8, 110.6),
                    (175.8, 108.9), (177.89, 108.9)])
    L.pour("VSYS", [(177.89, 113.0), (177.59, 113.0), (177.59, 113.4), (175.8, 113.4),
                    (175.8, 115.1), (177.89, 115.1)])
    L.via_array("VSYS", [176.3, 177.1], [110.1, 114.5])
    L.via_array("VBUS_EXT", [178.75], [109.5, 114.6])
    # CC はプラグ端子のすぐ左でビアに落とし、裏面で STUSB4500 へ
    L.stub("CC2_EXT", "J2", "B5", (181.25, 110.25), (181.2, 110.6), width=0.25)
    L.stub("CC1_EXT", "J2", "A5", (181.25, 113.25), (181.2, 112.9), width=0.25)
    L.stub("VBUS_EXT", "D1", "1", (178.6, 101.3))
    L.stub("VBUS_EXT", "C3", "1", (184.0, 117.4))
    L.stub("VBUS_EXT", "R17", "1", (178.9, 117.8))
    L.stub("VBUS_EXT", "R13", "1", (171.2, 101.1))
    L.routes.append(("EXT_DVDT", "F", 0.2, [L.pad("C7", "1"), L.pad("U2", "7")]))
    # U2 右側 (J2 側) の信号ピンは VBUS ポリゴンに挟まれるので、決め打ちのビアで裏面へ逃がす
    for net, pin, via in (("EXT_FLT", "4", (179.9, 110.55)), ("AUX_OFF", "3", (179.95, 111.55)),
                          ("EXT_OVLO", "2", (180.35, 112.35)), ("EXT_EN", "1", (179.75, 113.25))):
        pad = L.pad("U2", pin)
        L.routes.append((net, "F", 0.2, [pad, (179.5, pad[1]), via]))
        L.vias.append((net, *via))
    # EXT_OVLO は U2 と J2 の隙間 (x=180 付近) を裏面で下り、分圧抵抗 R19 に入る
    # VBUS_EXT のビア列 (x=178.75 / 179.9 / 180.7) の隙間 x=179.32 を抜け、R17 のビアを避けて x=178.2 へ寄る
    ovlo_end = (178.2, 119.6)
    L.routes.append(("EXT_OVLO", "B", 0.2, [(180.35, 112.35), (180.35, 113.85), (179.32, 113.85), (179.32, 115.6),
                                            (178.2, 116.8), ovlo_end]))
    L.vias.append(("EXT_OVLO", *ovlo_end))
    L.routes.append(("EXT_OVLO", "F", 0.2, [ovlo_end, (179.3, 120.0), L.pad("R19", "1"), L.pad("R18", "2")]))
    L.routes.append(("EXT_ILM", "F", 0.2, [L.pad("R21", "1"), (176.4, 112.23), L.pad("U2", "9")]))
    L.routes.append(("GND", "F", 0.2, [L.pad("U2", "8"), (176.05, 111.8)]))
    L.vias.append(("GND", 176.05, 111.8))
    L.routes.append(("VBUS_EXT", "F", 0.3, [L.pad("U4", "24"), L.pad("C4", "1")]))
    # STUSB4500 の SCL は右側ピンからすぐ裏面へ
    L.routes.append(("I2C_SCL", "F", 0.2, [L.pad("U4", "7"), (173.5, 107.3)]))
    L.vias.append(("I2C_SCL", 173.5, 107.3))
    # SDA も同じく U4 の脇でビアに落とす (SCL のビアとは 1.6mm 離す)
    L.routes.append(("I2C_SDA", "F", 0.2, [L.pad("U4", "8"), (173.3, 106.75), (174.2, 105.8)]))
    L.vias.append(("I2C_SDA", 174.2, 105.8))
    L.stub("VBUS_EXT", "C4", "1", (167.4, 108.4))


def _pc_input(L: Layout, kind: str):
    if kind == "c":
        # プラグ VBUS 2 端子 → 右の小ポリゴン → 3 本のビア
        L.pour("VBUS_PC", [(106.62, 118.1), (108.6, 118.1), (108.6, 120.0), (106.8, 120.0),
                           (106.8, 118.9), (106.62, 118.9)])
        L.via_array("VBUS_PC", [107.45], [118.55, 119.55])
        L.vias.append(("VBUS_PC", 108.25, 119.1))
        # CC は D+ と VBUS の間から出るので、VBUS ポリゴンの右を回して Rd と ADC 抵抗へ
        L.routes.append(("CC_PC", "F", 0.2, [L.pad("J1", "A5"), (109.1, 117.75), (109.1, 120.5),
                                             (108.2, 121.6), L.pad("R1", "1")]))
        L.routes.append(("CC_PC", "F", 0.2, [(108.2, 121.6), L.pad("R2", "1")]))
    else:
        # A 版のプラグはスルーホールなので、VBUS/GND は In2 プレーンへ直接つながる
        L.stub("VSYS", "R1", "1", (115.6, 113.2))
    # USBLC6 の VBUS ピン (C は右側、A は 180° 回転で左側)
    if kind == "c":
        L.stub("VBUS_PC", "U5", "5", (113.5, 116.3))
    else:
        L.stub("VBUS_PC", "U5", "5", (109.3, 117.0))
    # U3: IN 帯 x≈112.77 (左)、OUT 帯 x≈113.26 (右)。帯の上下端から引き出す
    L.pour("VBUS_PC", [(112.62, 123.35), (112.93, 123.35), (112.93, 120.3), (110.6, 120.3),
                       (110.6, 122.2), (112.42, 122.2), (112.42, 123.0), (112.62, 123.0)])
    L.pour("VBUS_PC", [(112.62, 125.65), (112.93, 125.65), (112.93, 127.9), (111.9, 127.9),
                       (111.9, 126.2), (112.62, 126.2)])
    L.via_array("VBUS_PC", [111.2, 112.0], [120.9])
    # U3 の左側信号は裏面へ逃がす
    L.routes.append(("PC_EN", "F", 0.2, [L.pad("U3", "1"), L.pad("R7", "1"), (111.0, 122.6)]))
    L.vias.append(("PC_EN", 111.0, 122.6))
    L.routes.append(("PC_FLT", "F", 0.2, [L.pad("U3", "4"), (111.25, 126.45)]))
    L.vias.append(("PC_FLT", 111.25, 126.45))  # 裏面から MCU へ
    # eFuse 周りは混雑して自動配線が抜けられないので、基板下側の空き地まで裏面で引き出しておく
    L.routes.append(("PC_FLT", "B", 0.2, [(111.25, 126.45), (111.25, 130.0), (117.0, 131.0)]))
    L.vias.append(("PC_FLT", 117.0, 131.0))
    L.routes.append(("PC_OVLO", "F", 0.2, [L.pad("U3", "2"), L.pad("R10", "2"), L.pad("R11", "1")]))
    L.vias.append(("VBUS_PC", 112.0, 127.3))
    L.pour("VSYS", [(113.13, 123.35), (113.41, 123.35), (113.41, 122.2), (113.6, 122.2),
                    (113.6, 120.3), (115.6, 120.3), (115.6, 122.4), (113.13, 122.4)])
    L.pour("VSYS", [(113.13, 125.65), (113.41, 125.65), (113.41, 126.9), (115.0, 126.9),
                    (115.0, 127.9), (113.13, 127.9)])
    L.via_array("VSYS", [114.2, 115.0], [121.0])
    L.vias.append(("VSYS", 114.3, 127.4))
    # LDO: VIN/EN はそれぞれビアで In2 の VBUS_PC へ (間の GND ピンの逃げ道を残す)
    L.stub("VBUS_PC", "U8", "1", (118.4, 102.0))
    L.stub("VBUS_PC", "U8", "3", (115.6, 102.0))
    L.stub("VBUS_PC", "C43", "1", (114.4, 102.6))


def _in2_planes(L: Layout):
    vbus_pc = [(100.3, 100.3), (121.0, 100.3), (121.0, 108.0), (114.0, 108.0), (114.0, 119.5),
               (113.28, 119.5), (113.28, 133.7), (100.3, 133.7)]
    vsys = [(114.4, 108.4), (121.4, 108.4), (121.4, 100.3), (165.6, 100.3), (165.6, 109.4),
            (177.4, 109.4), (177.4, 119.3), (156.0, 119.3), (156.0, 133.7), (113.6, 133.7),
            (113.6, 120.0), (114.4, 120.0)]
    p12 = rect(156.4, 119.7, 189.7, 133.7)
    vbus_ext = [(166.0, 100.3), (189.7, 100.3), (189.7, 119.3), (177.8, 119.3), (177.8, 109.0),
                (166.0, 109.0)]
    planes = [("VBUS_PC", vbus_pc), ("VSYS", vsys), ("+12V", p12), ("VBUS_EXT", vbus_ext)]
    for net, pts in planes:
        L.pour(net, pts, layer="In2", priority=1, keepout=False)
    return planes


def config(kind: str) -> BoardConfig:
    module = circuit.variant(kind)
    placements = {**COMMON, **VARIANT[kind]}
    L = Layout(placements, module.COMPONENTS)
    _pc_input(L, kind)
    _power_stage(L)
    _pd_input(L)
    planes = _in2_planes(L)
    out = ROOT / f"fanctl_{kind}" / f"fanctl_{kind}.kicad_pcb"
    return BoardConfig(
        name=f"fanctl_{kind}",
        module=module,
        output=out,
        origin=(X0, Y0),
        size=(W, H),
        placements=placements,
        holes=[],
        clearance=0.14,
        copper_layers=4,
        avoid_reference_routing=True,
        power_track_width=0.3,
        unrouted_nets=UNROUTED,
        auto_via_nets={"GND"},
        pad_via_skip={("U1", "24"), ("U6", "19"), ("U1", "15"), ("U2", "8"), ("C12", "2")},
        pad_vias={
            # RP2040 と STUSB4500 の露出パッドは 2x2 のビアで In1 へ
            ("U6", "57"): [(-0.8, -0.8), (0.8, -0.8), (-0.8, 0.8), (0.8, 0.8)],
            ("U4", "25"): [(-0.7, -0.7), (0.7, -0.7), (-0.7, 0.7), (0.7, 0.7)],
        },
        route_keepouts=L.keepouts,
        power_zones=L.zones,
        pre_routes=L.routes,
        pre_vias=L.vias,
        zone_keepouts=[("In2", (158.85, 118.95, 159.85, 119.95))],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["c", "a"])
    parser.add_argument("--ses", type=Path)
    args = parser.parse_args()
    cfg = config(args.kind)
    if args.ses:
        import_and_finish(cfg, args.ses)
    else:
        build_board(cfg)
    print("wrote", cfg.output)


if __name__ == "__main__":
    main()
