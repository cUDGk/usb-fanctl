"""このプロジェクト固有のシンボルのピン表。

ピン番号はフットプリントのパッド名と一致させる（lib/fanctl.pretty は
easyeda2kicad で LCSC から取得したもの）。各表はデータシートのピン表と照合済み。
"""

from __future__ import annotations


def _side(pins: list[tuple[str, str, str]], x: float, angle: float, top: float) -> dict:
    """(番号, 名前, 電気種別) の列を x 側に 2.54mm 間隔で上から並べる。"""
    return {
        number: {"name": name, "type": kind, "at": (x, top - 2.54 * i), "angle": angle}
        for i, (number, name, kind) in enumerate(pins)
        if number
    }


def _box(left, right, width=20.32):
    rows = max(len(left), len(right))
    top = 2.54 * (rows - 1) / 2
    half = width / 2 + 2.54
    # top は 1.27mm グリッド上に乗る (行数が偶数でも 2.54 の半分刻み)
    pins = _side(left, -half, 0, top)
    pins.update(_side(right, half, 180, top))
    return pins, width, 2.54 * rows + 2.54


# TPS55288 VQFN-HR-26 (TI SLVSF01B Table 5-1)
TPS55288 = _box(
    [
        ("3", "VIN", "power_in"),
        ("4", "EN/UVLO", "input"),
        ("5", "SCL", "input"),
        ("6", "SDA", "bidirectional"),
        ("7", "DITH/SYNC", "passive"),
        ("8", "FSW", "passive"),
        ("15", "MODE", "passive"),
        ("16", "CDC", "output"),
        ("17", "ILIM", "passive"),
        ("18", "COMP", "passive"),
        ("10", "AGND", "power_in"),
        ("9", "PGND", "power_in"),
        ("24", "PGND", "power_in"),
    ],
    [
        ("2", "DR1H", "output"),
        ("1", "DR1L", "output"),
        ("22", "BOOT1", "passive"),
        ("23", "SW1", "passive"),
        ("21", "SW2", "passive"),
        ("25", "SW2", "passive"),
        ("20", "BOOT2", "passive"),
        ("11", "VOUT", "power_out"),
        ("26", "VOUT", "passive"),  # 同一出力の 2 本目。power_out 重複の ERC を避ける
        ("12", "ISP", "input"),
        ("13", "ISN", "input"),
        ("14", "FB/INT", "open_collector"),
        ("19", "VCC", "power_out"),
    ],
    width=22.86,
)

# TPS25947 RPW QFN-10 (TI SLVSFC9C Table 5-1, TPS259470x の機能名)
TPS259470 = _box(
    [
        ("5", "IN", "power_in"),
        ("1", "EN/UVLO", "input"),
        ("2", "OVLO", "input"),
        ("7", "DVDT", "passive"),
        ("10", "ITIMER", "passive"),
    ],
    [
        ("6", "OUT", "passive"),  # 2 個を OR 接続するので power_out 同士の ERC 衝突を避ける
        ("3", "AUXOFF", "open_collector"),
        ("4", "FLT", "open_collector"),
        ("9", "ILM", "passive"),
        ("8", "GND", "power_in"),
    ],
)

# STUSB4500 QFN-24 (ST DS12499 Rev5 Table 1)。EP はパッド 25。
STUSB4500 = _box(
    [
        ("24", "VDD", "power_in"),
        ("18", "VBUS_VS_DISCH", "passive"),
        ("2", "CC1", "bidirectional"),
        ("1", "CC1DB", "passive"),
        ("4", "CC2", "bidirectional"),
        ("5", "CC2DB", "passive"),
        ("6", "RESET", "input"),
        ("7", "SCL", "input"),
        ("8", "SDA", "bidirectional"),
        ("12", "ADDR0", "input"),
        ("13", "ADDR1", "input"),
        ("22", "VSYS", "power_in"),
        ("3", "NC", "no_connect"),
    ],
    [
        ("21", "VREG_1V2", "power_out"),
        ("23", "VREG_2V7", "power_out"),
        ("19", "ALERT", "open_collector"),
        ("11", "ATTACH", "open_collector"),
        ("20", "POWER_OK2", "open_collector"),
        ("14", "POWER_OK3", "open_collector"),
        ("15", "GPIO", "open_collector"),
        ("16", "VBUS_EN_SNK", "open_collector"),
        ("17", "A_B_SIDE", "open_collector"),
        ("9", "DISCH", "passive"),
        ("10", "GND", "power_in"),
        ("25", "EP", "power_in"),
    ],
    width=25.4,
)

# CSD18543Q3A VSONP-8: 1-3=S, 4=G, 5-8 と露出パッド 9=D (TI SLPS438)
NMOS_VSONP8 = _box(
    [("4", "G", "input")],
    [
        ("5", "D", "passive"),
        ("6", "D", "passive"),
        ("7", "D", "passive"),
        ("8", "D", "passive"),
        ("9", "D", "passive"),
        ("1", "S", "passive"),
        ("2", "S", "passive"),
        ("3", "S", "passive"),
    ],
    width=10.16,
)

# SOT-23 小信号 N-MOSFET (2N7002): 1=G, 2=S, 3=D
NMOS_SOT23 = _box(
    [("1", "G", "input")],
    [("3", "D", "passive"), ("2", "S", "passive")],
    width=10.16,
)

# HRO TYPE-C-31-G-10 (USB2.0 Type-C プラグ, 12 ピン片面実装)。1-10 はシェル/ラッチ。
USBC_PLUG_G10 = _box(
    [
        ("A4", "VBUS", "passive"),
        ("B9", "VBUS", "passive"),
        ("A5", "CC", "bidirectional"),
        ("B5", "VCONN", "passive"),
        ("A6", "D+", "bidirectional"),
        ("A7", "D-", "bidirectional"),
        ("A10", "RX2-", "passive"),
        ("A11", "RX2+", "passive"),
        ("B2", "TX2+", "passive"),
        ("B3", "TX2-", "passive"),
        ("A1", "GND", "passive"),
        ("B12", "GND", "passive"),
    ],
    [(str(n), "SHIELD", "passive") for n in range(1, 11)],
    width=15.24,
)

# USB2.0-A90-G (Type-A プラグ, 右アングル・スルーホール)。5/6 はシェル。
USBA_PLUG_TH = _box(
    [
        ("1", "VBUS", "passive"),
        ("2", "D-", "bidirectional"),
        ("3", "D+", "bidirectional"),
        ("4", "GND", "passive"),
    ],
    [("5", "SHIELD", "passive"), ("6", "SHIELD", "passive")],
    width=15.24,
)

# 4 ピン PWM ファンヘッダ (Intel 4-wire 仕様のピン順)
FAN4 = _box(
    [
        ("1", "GND", "passive"),
        ("2", "+12V", "passive"),
        ("3", "TACH", "passive"),
        ("4", "PWM", "passive"),
    ],
    [],
    width=10.16,
)
