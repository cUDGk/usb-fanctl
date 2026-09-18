"""USB ファンコントローラ回路（Type-C プラグ版 / Type-A プラグ版の共通定義）。

構成:
  PC 側 USB プラグ ─ D+/D- ─ RP2040 (USB CDC で PC から制御)
       └ VBUS ─ eFuse U3 (補助, 2.2A 制限) ─┐
  USB-C レセプタクル ─ STUSB4500 (PD シンク)       ├─ VSYS ─ TPS55288 昇降圧 ─ 12V ─ 4 ピン PWM ファン
       └ VBUS ─ eFuse U2 (優先, 2.8A 制限) ─┘
- U2/U3 は TPS259470A の優先電源 MUX 構成 (TI SLVSFC9C 図 8-10)。外部 PD 電源が
  有効な間は U2 の AUXOFF が U3 の OVLO を持ち上げて PC 側経路を切る。両者とも
  逆流阻止付きなので、外部の 20V が PC の VBUS に回り込むことはない。
- TPS55288 は 5〜20V 入力から 12V を作る。出力電流制限 (10mΩ センス) と CDC ピンの
  電流モニタを FW が I2C/ADC で使い、給電元の許容電力に合わせてファン電力を絞る。
- 部品定数は TPS55288EVM-045 (SLVUBO4B) と各データシートの式に基づく。

使い方: variant("c") / variant("a") が pcbgen に渡す回路モジュール相当を返す。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

import custom_symbols as cs  # noqa: E402
from kischgen import Schematic  # noqa: E402

FP = "fanctl"  # プロジェクト内フットプリントライブラリ (lib/fanctl.pretty)
R0402 = "Resistor_SMD:R_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
R0805 = "Resistor_SMD:R_0805_2012Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"

CUSTOM = {
    "Custom:TPS55288": (cs.TPS55288, "TI 36V 16A buck-boost, VQFN-HR-26"),
    "Custom:TPS259470": (cs.TPS259470, "TI 23V 5.5A eFuse with AUXOFF, QFN-10"),
    "Custom:STUSB4500": (cs.STUSB4500, "ST USB PD sink controller, QFN-24"),
    "Custom:NMOS_VSONP8": (cs.NMOS_VSONP8, "N-MOSFET VSONP-8"),
    "Custom:NMOS_SOT23": (cs.NMOS_SOT23, "N-MOSFET SOT-23 (G S D)"),
    "Custom:USBC_PLUG_G10": (cs.USBC_PLUG_G10, "USB2.0 Type-C plug HRO TYPE-C-31-G-10"),
    "Custom:USBA_PLUG_TH": (cs.USBA_PLUG_TH, "USB2.0 Type-A plug, right angle THT"),
    "Custom:FAN4": (cs.FAN4, "4-pin PWM fan header"),
}


def R(ref, value, lcsc, fp=R0402):
    return dict(lib="Device:R", ref=ref, value=value, fp=fp, lcsc=lcsc)


def C(ref, value, lcsc, fp=C0402):
    return dict(lib="Device:C", ref=ref, value=value, fp=fp, lcsc=lcsc)


def _common_components():
    return [
        # --- 外部 PD 入力 -------------------------------------------------
        dict(lib="Connector:USB_C_Receptacle_USB2.0_16P", ref="J2", value="PD IN",
             fp="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", lcsc="C165948"),
        # 20V PD に対し Vrwm 22V。TPS25947 の絶対最大 28V より前でクランプさせる。
        dict(lib="Device:D_Zener", ref="D1", value="SMAJ22A", fp="Diode_SMD:D_SMA", lcsc="C908773"),
        # CC は BMC 通信線。受信側許容容量 200-600pF に対し 23pF で問題ない。
        dict(lib="Custom:PESD24VS2UT", ref="D4", value="PESD24VS2UT", fp="Package_TO_SOT_SMD:SOT-23", lcsc="C477999"),
        C("C3", "4.7uF 50V", "C29823", C1206),  # USB Type-C シンクの VBUS 容量上限 10uF 以内
        dict(lib="Custom:STUSB4500", ref="U4", value="STUSB4500QTR", fp=f"{FP}:QFN-24_L4.0-W4.0-P0.50-BL-EP2.8", lcsc="C2678061"),
        C("C4", "1uF 50V", "C15849", C0603),
        C("C5", "1uF", "C52923"),
        C("C6", "1uF", "C52923"),
        R("R13", "1k", "C17513", R0805),  # VBUS_VS_DISCH 放電電流制限 (20V/1k=20mA < 50mA)
        R("R14", "100k", "C25741"),
        R("R15", "10k", "C25744"),
        R("R16", "10k", "C25744"),
        dict(lib="Custom:TPS259470", ref="U2", value="TPS259470ARPWR", fp=f"{FP}:VQFN-10_L2.0-W2.0-P0.45-TL", lcsc="C3662799"),
        # EN/OVLO 3 段分圧: EN 立上り 1.2V×1375/375 = 4.4V, OVLO 1.2V×1375/75 = 22.0V。
        # 20V 時 EN=5.45V だが上側 1M (>=350k) 経由なので TI 推奨条件内。
        R("R17", "1M", "C26083"),
        R("R18", "300k", "C25774"),
        R("R19", "75k", "C25798"),
        C("C7", "2.2nF 50V", "C1531"),  # dVdt: 2000/2200 = 0.9V/ms で 60uF 充電でも 55mA
        R("R21", "1.2k", "C25862"),  # ILIM = 3334/1200 = 2.78A (USB-C 3A ケーブル以内)
        R("R22", "10k", "C25744"),
        R("R23", "10k", "C25744"),  # ILM は 50pF 以下の負荷制約があるため ADC とは抵抗で分離
        # --- PC 側 VBUS 経路 ----------------------------------------------
        C("C1", "4.7uF", "C19666", C0603),
        dict(lib="Power_Protection:USBLC6-2SC6", ref="U5", value="USBLC6-2SC6", fp="Package_TO_SOT_SMD:SOT-23-6", lcsc="C7519"),
        R("R4", "22R", "C25092"),
        R("R5", "22R", "C25092"),
        dict(lib="Custom:TPS259470", ref="U3", value="TPS259470ARPWR", fp=f"{FP}:VQFN-10_L2.0-W2.0-P0.45-TL", lcsc="C3662799"),
        R("R6", "1.5k", "C25867"),  # ILIM = 2.22A。実際の上限は FW が PC ポートの能力から決める
        C("C2", "2.2nF 50V", "C1531"),  # MUX では高い方の電源 (20V) を基準に耐圧を選ぶ
        R("R7", "100k", "C25741"),
        R("R8", "10k", "C25744"),
        # AUXOFF(開放ドレイン) プルアップと U3 OVLO 分圧。U2 無給電時に AUXOFF が
        # 最大 1V 浮いても OVLO は 0.67V で U3 を止めない。有効時は OVLO=1.5V。
        R("R9", "47k", "C25792"),
        R("R10", "33k", "C25779"),
        R("R11", "68k", "C36871"),
        R("R12", "10k", "C25744"),
        # --- 昇降圧コンバータ --------------------------------------------
        dict(lib="Custom:TPS55288", ref="U1", value="TPS55288RPMR", fp=f"{FP}:VQFN-HR-26_L4.0-W3.5_TPS55288RPMR", lcsc="C2864583"),
        dict(lib="Custom:NMOS_VSONP8", ref="Q1", value="CSD18543Q3A", fp=f"{FP}:VSONP-8_L3.1-W3.1-P0.65-LS3.5-BL", lcsc="C840100"),
        dict(lib="Custom:NMOS_VSONP8", ref="Q2", value="CSD18543Q3A", fp=f"{FP}:VSONP-8_L3.1-W3.1-P0.65-LS3.5-BL", lcsc="C840100"),
        R("R24", "1R", "C25086"),
        R("R25", "1R", "C25086"),
        C("C8", "100nF", "C1525"),
        C("C9", "100nF", "C1525"),
        dict(lib="Device:L", ref="L1", value="4.7uH IHLP2525CZ", fp="Inductor_SMD:L_Vishay_IHLP-2525", lcsc="C553961"),
        C("C10", "10uF 50V", "C13585", C1206),
        C("C11", "10uF 50V", "C13585", C1206),
        C("C12", "1uF 50V", "C15849", C0603),
        dict(lib="Device:C_Polarized", ref="C13", value="47uF 35V", fp="Capacitor_SMD:CP_Elec_6.3x5.4", lcsc="C2836440"),
        C("C14", "22uF 25V", "C12891", C1206),
        C("C15", "22uF 25V", "C12891", C1206),
        C("C16", "22uF 25V", "C12891", C1206),
        C("C17", "22uF 25V", "C12891", C1206),
        C("C18", "1uF 50V", "C15849", C0603),
        # 出力バルクは低 ESR ハイブリッド。EVM (220uF ポリマー) より少ないので交差周波数は約 5kHz に上がるが、
        # 5V 昇圧時の RHPZ/5 (約 13kHz) より十分低い。
        dict(lib="Device:C_Polarized", ref="C19", value="100uF 25V hybrid", fp="Capacitor_SMD:CP_Elec_6.3x5.8", lcsc="C454668"),
        R("R26", "10mR 1W", "C105362", R1206),  # 出力電流制限: 25mV で 2.5A (レジスタで可変)
        C("C20", "100nF", "C1525"),
        C("C21", "4.7uF", "C19666", C0603),
        R("R27", "49.9k", "C25897"),  # fsw = 1000/(0.05×49.9+20)... = 400kHz (EVM 値)
        C("C22", "10nF", "C15195"),  # 周波数ディザ
        R("R28", "56k", "C25796"),  # 平均インダクタ電流制限 330000/56k = 5.9A
        R("R29", "56k", "C25796"),  # 位相補償 (EVM: 56.2k / 4.7nF / 100pF)
        C("C23", "4.7nF", "C1538"),
        C("C24", "100pF", "C1546"),
        R("R30", "150k", "C25755"),  # CDC (EVM 値)。CDC = 20×(ISP-ISN) を ADC で読む
        R("R31", "10k", "C25744"),
        C("C25", "1nF", "C1523"),
        R("R32", "100k", "C25741"),
        R("R33", "10k", "C25744"),
        C("C26", "10uF 25V", "C15850", C0805),
        C("C27", "100nF 50V", "C307331"),
        dict(lib="Device:D_Zener", ref="D2", value="SMAJ15A", fp="Diode_SMD:D_SMA", lcsc="C908769"),
        # --- ファン -------------------------------------------------------
        dict(lib="Custom:FAN4", ref="J3", value="FAN 4P", fp="Connector:FanPinHeader_1x04_P2.54mm_Vertical", lcsc="C240840"),
        dict(lib="Custom:NMOS_SOT23", ref="Q3", value="2N7002", fp="Package_TO_SOT_SMD:SOT-23", lcsc="C8545"),
        R("R34", "100R", "C25076"),
        R("R35", "100k", "C25741"),
        R("R36", "10k", "C25744"),
        R("R37", "10k", "C25744"),  # TACH が万一 12V プッシュプルでも注入電流を 1mA 未満に抑える
        # --- MCU ----------------------------------------------------------
        dict(lib="MCU_RaspberryPi:RP2040", ref="U6", value="RP2040", fp="Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", lcsc="C2040"),
        dict(lib="Memory_Flash:W25Q16JVSS", ref="U7", value="W25Q16JVSSIQ", fp="Package_SO:SOIC-8_5.3x5.3mm_P1.27mm", lcsc="C131025"),
        dict(lib="Regulator_Linear:AP2112K-3.3", ref="U8", value="AP2112K-3.3", fp="Package_TO_SOT_SMD:SOT-23-5", lcsc="C51118"),
        dict(lib="Device:Crystal_GND24", ref="Y1", value="12MHz ABM8-272-T3", fp="Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", lcsc="C20625731"),
        C("C28", "15pF", "C1548"),
        C("C29", "15pF", "C1548"),
        R("R38", "1k", "C11702"),
        *[C(f"C{n}", "100nF", "C1525") for n in range(30, 38)],  # IOVDD×6, DVDD×2
        C("C38", "1uF", "C52923"),
        C("C39", "1uF", "C52923"),
        C("C40", "100nF", "C1525"),
        C("C41", "100nF", "C1525"),
        C("C42", "100nF", "C1525"),
        C("C43", "1uF", "C52923"),
        C("C44", "10uF", "C19702", C0603),
        dict(lib="Switch:SW_Push", ref="SW1", value="BOOTSEL", fp=f"{FP}:SW-SMD_4P-L5.1-W5.1-P3.70-LS6.5-TL_H1.5", lcsc="C318884"),
        R("R40", "1k", "C11702"),
        dict(lib="Device:LED", ref="D3", value="LED", fp="LED_SMD:LED_0603_1608Metric", lcsc="C2286"),
        R("R41", "1k", "C11702"),
        R("R42", "4.7k", "C25900"),
        R("R43", "4.7k", "C25900"),
    ]


def _common_nets():
    return [
        # 電源レール
        ("VBUS_EXT", True, [("J2", "name:VBUS"), ("D1", "1"), ("C3", "1"), ("U4", "24"), ("C4", "1"),
                            ("R13", "1"), ("U2", "5"), ("R17", "1")]),
        ("VBUS_PC", True, [("J1", "name:VBUS"), ("C1", "1"), ("U5", "5"), ("U3", "5"), ("U8", "1"),
                           ("U8", "3"), ("C43", "1")]),
        ("VSYS", True, [("U2", "6"), ("U3", "6"), ("Q1", "name:D"), ("U1", "3"), ("C10", "1"), ("C11", "1"),
                        ("C12", "1"), ("C13", "1")]),
        ("VOUT_RAW", True, [("U1", "name:VOUT"), ("U1", "12"), ("R26", "1"), ("C14", "1"), ("C15", "1"),
                            ("C16", "1"), ("C17", "1"), ("C18", "1"), ("C19", "1"), ("C20", "1")]),
        ("+12V", True, [("R26", "2"), ("U1", "13"), ("C20", "2"), ("C26", "1"), ("C27", "1"), ("D2", "1"),
                        ("J3", "2")]),
        ("+3V3", False, [("U8", "5"), ("C44", "1"), ("U6", "name:IOVDD"), ("U6", "name:VREG_VIN"),
                        ("U6", "name:USB_VDD"), ("U6", "name:ADC_AVDD"), ("U7", "8"), ("C30", "1"),
                        ("C31", "1"), ("C32", "1"), ("C33", "1"), ("C34", "1"), ("C35", "1"), ("C38", "1"),
                        ("C40", "1"), ("C41", "1"), ("C42", "1"), ("R42", "1"), ("R43", "1"),
                        ("R8", "1"), ("R9", "1"), ("R15", "1"), ("R16", "1"), ("R22", "1"), ("R33", "1"),
                        ("R36", "1")]),
        ("+1V1", False, [("U6", "name:VREG_VOUT"), ("U6", "name:DVDD"), ("C36", "1"), ("C37", "1"), ("C39", "1")]),
        ("GND", True, [
            ("J2", "name:GND"), ("J2", "name:SHIELD"), ("D1", "2"), ("D4", "3"), ("C3", "2"),
            ("U4", "10"), ("U4", "25"), ("U4", "22"), ("U4", "12"), ("U4", "13"), ("C4", "2"), ("C5", "2"),
            ("C6", "2"), ("R14", "2"), ("U2", "8"), ("R19", "2"), ("C7", "2"), ("R21", "2"),
            ("C1", "2"), ("U5", "2"), ("U3", "8"), ("R6", "2"), ("C2", "2"), ("R7", "2"), ("R11", "2"),
            ("U1", "name:AGND"), ("U1", "name:PGND"), ("U1", "15"), ("Q2", "name:S"),
            ("C10", "2"), ("C11", "2"), ("C12", "2"), ("C13", "2"), ("C14", "2"), ("C15", "2"), ("C16", "2"),
            ("C17", "2"), ("C18", "2"), ("C19", "2"), ("C21", "2"), ("R27", "2"), ("C22", "2"), ("R28", "2"),
            ("C23", "2"), ("C24", "2"), ("R30", "2"), ("C25", "2"), ("R32", "2"), ("C26", "2"), ("C27", "2"),
            ("D2", "2"), ("J3", "1"), ("Q3", "2"), ("R35", "2"),
            ("U6", "name:GND"), ("U6", "name:TESTEN"), ("U7", "4"), ("U8", "2"), ("Y1", "name:G"),
            ("C28", "2"), ("C29", "2"), ("C30", "2"), ("C31", "2"), ("C32", "2"), ("C33", "2"), ("C34", "2"),
            ("C35", "2"), ("C36", "2"), ("C37", "2"), ("C38", "2"), ("C39", "2"), ("C40", "2"), ("C41", "2"),
            ("C42", "2"), ("C43", "2"), ("C44", "2"), ("SW1", "2"), ("D3", "1"),
        ]),
        # 外部 PD 側
        ("CC1_EXT", False, [("J2", "A5"), ("U4", "2"), ("U4", "1"), ("D4", "1")]),
        ("CC2_EXT", False, [("J2", "B5"), ("U4", "4"), ("U4", "5"), ("D4", "2")]),
        ("VBUS_DISCH", False, [("R13", "2"), ("U4", "18")]),
        ("PD_1V2", False, [("U4", "21"), ("C5", "1")]),
        ("PD_2V7", False, [("U4", "23"), ("C6", "1")]),
        ("PD_RESET", False, [("U4", "6"), ("R14", "1")]),
        ("PD_ATTACH", False, [("U4", "11"), ("R15", "2"), ("U6", "name:GPIO9")]),
        ("PD_ALERT", False, [("U4", "19"), ("R16", "2"), ("U6", "name:GPIO10")]),
        ("EXT_EN", False, [("U2", "1"), ("R17", "2"), ("R18", "1")]),
        ("EXT_OVLO", False, [("U2", "2"), ("R18", "2"), ("R19", "1")]),
        ("EXT_DVDT", False, [("U2", "7"), ("C7", "1")]),
        ("EXT_ILM", False, [("U2", "9"), ("R21", "1"), ("R23", "1")]),
        ("ADC_ILM_EXT", False, [("R23", "2"), ("U6", "name:GPIO28/ADC2")]),
        ("EXT_FLT", False, [("U2", "4"), ("R22", "2"), ("U6", "name:GPIO8")]),
        ("AUX_OFF", False, [("U2", "3"), ("R9", "2"), ("R10", "1")]),
        ("PC_OVLO", False, [("U3", "2"), ("R10", "2"), ("R11", "1")]),
        # PC 側
        # USBLC6 はフロースルー配置 (1→6 と 3→4 が直線)。基板上の並びに合わせ D- を I/O1 側にする
        ("USB_DM_CONN", False, [("J1", "name:D-"), ("U5", "1"), ("U5", "6"), ("R5", "1")]),
        ("USB_DP_CONN", False, [("J1", "name:D+"), ("U5", "3"), ("U5", "4"), ("R4", "1")]),
        ("USB_DP", False, [("R4", "2"), ("U6", "name:USB_DP")]),
        ("USB_DM", False, [("R5", "2"), ("U6", "name:USB_DM")]),
        ("PC_EN", False, [("U3", "1"), ("R7", "1"), ("U6", "name:GPIO6")]),
        ("PC_FLT", False, [("U3", "4"), ("R8", "2"), ("U6", "name:GPIO7")]),
        ("PC_DVDT", False, [("U3", "7"), ("C2", "1")]),
        ("PC_ILM", False, [("U3", "9"), ("R6", "1"), ("R12", "1")]),
        ("ADC_ILM_PC", False, [("R12", "2"), ("U6", "name:GPIO29/ADC3")]),
        # コンバータ
        ("BB_HDRV", False, [("U1", "2"), ("R24", "1")]),
        ("BB_HG", False, [("R24", "2"), ("Q1", "name:G")]),
        ("BB_LDRV", False, [("U1", "1"), ("R25", "1")]),
        ("BB_LG", False, [("R25", "2"), ("Q2", "name:G")]),
        ("SW1", True, [("Q1", "name:S"), ("Q2", "name:D"), ("U1", "23"), ("C8", "2"), ("L1", "1")]),
        ("BOOT1", False, [("U1", "22"), ("C8", "1")]),
        ("SW2", True, [("U1", "name:SW2"), ("C9", "2"), ("L1", "2")]),
        ("BOOT2", False, [("U1", "20"), ("C9", "1")]),
        ("BB_VCC", False, [("U1", "19"), ("C21", "1")]),
        ("BB_FSW", False, [("U1", "8"), ("R27", "1")]),
        ("BB_DITH", False, [("U1", "7"), ("C22", "1")]),
        ("BB_ILIM", False, [("U1", "17"), ("R28", "1")]),
        ("BB_COMP", False, [("U1", "18"), ("R29", "1"), ("C24", "1")]),
        ("BB_COMP_RC", False, [("R29", "2"), ("C23", "1")]),
        ("BB_CDC", False, [("U1", "16"), ("R30", "1"), ("R31", "1")]),
        ("ADC_IOUT", False, [("R31", "2"), ("C25", "1"), ("U6", "name:GPIO27/ADC1")]),
        ("BB_EN", False, [("U1", "4"), ("R32", "1"), ("U6", "name:GPIO4")]),
        ("BB_INT", False, [("U1", "14"), ("R33", "2"), ("U6", "name:GPIO5")]),
        ("I2C_SDA", False, [("U1", "6"), ("U4", "8"), ("R42", "2"), ("U6", "name:GPIO2")]),
        ("I2C_SCL", False, [("U1", "5"), ("U4", "7"), ("R43", "2"), ("U6", "name:GPIO3")]),
        # ファン
        ("FAN_PWM_MCU", False, [("U6", "name:GPIO0"), ("R34", "1")]),
        ("FAN_PWM_G", False, [("R34", "2"), ("R35", "1"), ("Q3", "1")]),
        ("FAN_PWM", False, [("Q3", "3"), ("J3", "4")]),
        ("FAN_TACH", False, [("J3", "3"), ("R36", "2"), ("R37", "1")]),
        ("FAN_TACH_MCU", False, [("R37", "2"), ("U6", "name:GPIO1")]),
        # MCU 周辺
        ("XIN", False, [("U6", "name:XIN"), ("Y1", "1"), ("C28", "1")]),
        ("XOUT", False, [("U6", "name:XOUT"), ("R38", "1")]),
        ("XOUT_R", False, [("R38", "2"), ("Y1", "3"), ("C29", "1")]),
        # RUN は RP2040 内蔵プルアップに任せる (外付け不要)
        ("QSPI_SS", False, [("U6", "56"), ("U7", "1"), ("R40", "1")]),
        ("BOOTSEL", False, [("R40", "2"), ("SW1", "1")]),
        ("QSPI_SCLK", False, [("U6", "name:QSPI_SCLK"), ("U7", "6")]),
        ("QSPI_SD0", False, [("U6", "name:QSPI_SD0"), ("U7", "5")]),
        ("QSPI_SD1", False, [("U6", "name:QSPI_SD1"), ("U7", "2")]),
        ("QSPI_SD2", False, [("U6", "name:QSPI_SD2"), ("U7", "3")]),
        ("QSPI_SD3", False, [("U6", "name:QSPI_SD3"), ("U7", "7")]),
        ("LED", False, [("U6", "name:GPIO11"), ("R41", "1")]),
        ("LED_A", False, [("R41", "2"), ("D3", "2")]),
    ]


def _variant_parts(kind: str):
    if kind == "c":
        comps = [
            dict(lib="Custom:USBC_PLUG_G10", ref="J1", value="USB-C PLUG", fp=f"{FP}:USB-C-SMD_TYPE-C-31-G-10", lcsc="C5370430"),
            R("R1", "5.1k", "C25905"),  # Rd: PC 側から見て USB デバイス
            R("R2", "1k", "C11702"),
        ]
        nets = [
            # CC の電圧で PC ポートの供給能力 (Default/1.5A/3A) を判定する
            ("CC_PC", False, [("J1", "A5"), ("R1", "1"), ("R2", "1")]),
            ("ADC_CC", False, [("R2", "2"), ("U6", "name:GPIO26/ADC0")]),
            ("GND", True, [("J1", "name:GND"), ("J1", "name:SHIELD"), ("R1", "2")]),
        ]
    elif kind == "a":
        comps = [
            dict(lib="Custom:USBA_PLUG_TH", ref="J1", value="USB-A PLUG", fp=f"{FP}:USB-A-TH_USB2.0-A90-G", lcsc="C53699947"),
            R("R1", "100k", "C25741"),  # VSYS 分圧 100k/15k: 22V でも ADC 2.87V
            R("R2", "15k", "C25756"),
        ]
        nets = [
            ("VSYS", True, [("R1", "1")]),
            ("ADC_VSYS", False, [("R1", "2"), ("R2", "1"), ("U6", "name:GPIO26/ADC0")]),
            ("GND", True, [("J1", "name:GND"), ("J1", "name:SHIELD"), ("R2", "2")]),
        ]
    else:
        raise ValueError(kind)
    return comps, nets


def _merge_nets(nets):
    merged: dict[str, tuple[bool, list]] = {}
    for name, power, endpoints in nets:
        if name in merged:
            merged[name][1].extend(endpoints)
        else:
            merged[name] = (power, list(endpoints))
    return [(name, power, eps) for name, (power, eps) in merged.items()]


def _place(components):
    """回路図上の配置。ラベルが重ならないよう種類ごとに格子へ並べる。"""
    big_x, small_col = 30.48, 0
    placed = []
    for comp in components:
        comp = dict(comp)
        if comp["lib"].startswith(("Custom:", "MCU_", "Memory_", "Connector:")) or comp["ref"] in ("U5", "U8", "Y1"):
            comp["at"] = (big_x, 60.96)
            big_x += 76.2
        else:
            col, row = divmod(small_col, 8)
            comp["at"] = (30.48 + row * 45.72, 142.24 + col * 25.4)
            comp["rot"] = 90
            small_col += 1
        placed.append(comp)
    return placed


PESD24VS2UT = {
    "1": {"name": "K1", "type": "passive", "at": (-10.16, 2.54), "angle": 0},
    "2": {"name": "K2", "type": "passive", "at": (-10.16, -2.54), "angle": 0},
    "3": {"name": "A", "type": "passive", "at": (10.16, 0), "angle": 180},
}


def variant(kind: str) -> SimpleNamespace:
    vcomps, vnets = _variant_parts(kind)
    components = _place(_common_components() + vcomps)
    nets = _merge_nets(_common_nets() + vnets)
    name = f"fanctl_{kind}"

    def build() -> Schematic:
        sch = Schematic(project_name=name, title=f"USB Fan Controller ({kind.upper()} plug)", paper="A1")
        for lib_id, ((pins, width, height), desc) in CUSTOM.items():
            sch.library.add_custom(lib_id, reference_prefix="U",
                                   description=desc, pins=pins, body_width=width, body_height=height)
        sch.library.add_custom("Custom:PESD24VS2UT", reference_prefix="D", description="dual 24V ESD",
                               pins=PESD24VS2UT)
        for comp in components:
            sch.add_symbol(comp["lib"], comp["ref"], comp["value"], comp["fp"], comp["at"], comp.get("rot", 0))
        for net, power, endpoints in nets:
            sch.connect(net, endpoints, power=power)
        # 出力ピン (TPS55288 VOUT, LDO, RP2040 VREG) が駆動するレール以外に PWR_FLAG を置く
        for rail, x in (("VBUS_EXT", 20), ("VBUS_PC", 30), ("VSYS", 40), ("SW1", 60),
                        ("SW2", 70), ("+12V", 80), ("GND", 110)):
            sch.add_power_flag(rail, (x * 2.54, 30 * 2.54))
        sch.mark_unused_pins()
        return sch

    return SimpleNamespace(__name__=name, COMPONENTS=components, NETS=nets, build=build)


if __name__ == "__main__":
    for kind in sys.argv[1:] or ["c", "a"]:
        out = ROOT / f"fanctl_{kind}" / f"fanctl_{kind}.kicad_sch"
        variant(kind).build().write(out)
        print("wrote", out)
