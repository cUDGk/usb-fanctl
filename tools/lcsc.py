"""LCSC / JLCPCB 部品検索ヘルパ。

使い方:
    python tools/lcsc.py search TPS55288 [more keywords...]
    python tools/lcsc.py code C2869617 [more codes...]
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def _get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data, UA), timeout=30) as r:
        return json.load(r)


def jlc_search(keyword: str) -> list[dict]:
    """JLCPCB 実装部品ライブラリ検索。Basic/Extended と在庫が分かる。"""
    res = _post(
        "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList",
        {"keyword": keyword, "currentPage": 1, "pageSize": 15},
    )
    page = (res.get("data") or {}).get("componentPageInfo") or {}
    return page.get("list") or []


def show(item: dict) -> None:
    prices = item.get("componentPrices") or []
    p = ", ".join(f"{x['startNumber']}+:${x['productPrice']}" for x in prices[:3])
    print(
        f"{item.get('componentCode'):>10} | {item.get('componentLibraryType'):8} | "
        f"stock {item.get('stockCount'):>7} | {item.get('componentModelEn')} | "
        f"{item.get('componentSpecificationEn')} | {p}"
    )


def main() -> None:
    mode, *args = sys.argv[1:]
    for arg in args:
        print(f"== {arg}")
        for item in jlc_search(arg):
            if mode == "code" and item.get("componentCode") != arg:
                continue
            show(item)


if __name__ == "__main__":
    main()
