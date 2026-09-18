"""受動部品の LCSC 番号候補を Basic/Preferred 優先で探す（部品選定の補助、一回きり）。"""

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


def search(keyword, library=None):
    body = {"keyword": keyword, "currentPage": 1, "pageSize": 30}
    if library:
        body["componentLibraryType"] = library
    req = urllib.request.Request(
        URL, json.dumps(body).encode(), {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    )
    data = json.load(urllib.request.urlopen(req, timeout=30))["data"]["componentPageInfo"]["list"] or []
    return data


for kw in sys.argv[1:]:
    rows = []
    for lib in ("base", None):
        for it in search(kw, lib):
            rows.append(it)
    seen = set()
    print("==", kw)
    rows.sort(key=lambda i: (i["componentLibraryType"] != "base", not i.get("preferredComponentFlag"), -i["stockCount"]))
    for it in rows:
        if it["componentCode"] in seen or it["stockCount"] < 500:
            continue
        seen.add(it["componentCode"])
        tag = "BASIC" if it["componentLibraryType"] == "base" else ("PREF" if it.get("preferredComponentFlag") else "ext")
        print(f"  {it['componentCode']:>9} {tag:5} {it['stockCount']:>8} {it['componentModelEn'][:28]:28} {it['describe'][:90]}")
        if len(seen) >= 4:
            break
