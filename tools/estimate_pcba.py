"""JLCPCB 経済 PCBA の部品費・拡張部品料を LCSC/JLC の公開 API から見積もる。

    python tools/estimate_pcba.py c 5
ログイン後の正式見積もりの前に目安を出すためのもの。手数料の単価は下の定数を参照。
"""

from __future__ import annotations

import csv
import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
EXT_FEE = 3.0  # 拡張部品 1 種あたり (Preferred は無料)


def lookup(code: str) -> dict:
    body = json.dumps({"keyword": code, "currentPage": 1, "pageSize": 10}).encode()
    req = urllib.request.Request(URL, body, {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
    items = json.load(urllib.request.urlopen(req, timeout=30))["data"]["componentPageInfo"]["list"] or []
    for it in items:
        if it["componentCode"] == code:
            return it
    raise KeyError(code)


def unit_price(item: dict, qty: int) -> float:
    best = None
    for p in item.get("componentPrices") or []:
        if qty >= p["startNumber"]:
            best = p["productPrice"]
    return best if best is not None else item["componentPrices"][0]["productPrice"]


def main(kind: str, boards: int):
    sys.stdout.reconfigure(encoding="utf-8")
    bom = ROOT / "order" / f"fanctl_{kind}" / f"fanctl_{kind}_bom.csv"
    rows = list(csv.DictReader(bom.open(encoding="utf-8")))
    total_parts = 0.0
    ext_types = 0
    out = []
    for r in rows:
        refs = r["Designator"].split(",")
        it = lookup(r["LCSC Part #"])
        need = len(refs) * boards
        # JLC は受動部品などに損耗分 (lossNumber) を上乗せし、最小実装数 (leastPatchNumber) 未満は切り上げる
        qty = max(need + int(it.get("lossNumber") or 0), int(it.get("leastPatchNumber") or 0), need)
        price = unit_price(it, qty)
        cost = qty * price
        total_parts += cost
        kind_tag = "basic" if it["componentLibraryType"] == "base" else (
            "pref" if it.get("preferredComponentFlag") else "EXT")
        if kind_tag == "EXT":
            ext_types += 1
        out.append((cost, r["LCSC Part #"], it["componentModelEn"][:24], kind_tag, qty, price, it["stockCount"]))
    for cost, code, model, tag, qty, price, stock in sorted(out, reverse=True):
        print(f"{code:>10} {model:24} {tag:5} qty {qty:4} x ${price:<8} = ${cost:7.2f}  stock {stock}")
    print(f"parts total ${total_parts:.2f}, extended types {ext_types} -> fee ${ext_types * EXT_FEE:.2f}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5)
