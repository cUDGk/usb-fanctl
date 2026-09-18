"""データシートを datasheets/ に落としてテキスト化する（第三者著作物なので git 管理外）。"""

from pathlib import Path
import sys
import urllib.request

import fitz

DS = {
    "tps55288": "https://www.ti.com/lit/ds/symlink/tps55288.pdf",
    "lm74700": "https://www.ti.com/lit/ds/symlink/lm74700-q1.pdf",
    "ina219": "https://www.ti.com/lit/ds/symlink/ina219.pdf",
    # ST 本家はスクリプトからの取得を弾くので LCSC のミラーを使う
    "stusb4500": "https://datasheet.lcsc.com/datasheet/pdf/544b1f3e32c1f05aafa0220c5ab5d05f.pdf",
    "rp2040_hw": "https://datasheets.raspberrypi.com/rp2040/hardware-design-with-rp2040.pdf",
}

out = Path(__file__).resolve().parents[1] / "datasheets"
out.mkdir(exist_ok=True)
for name in sys.argv[1:] or DS:
    pdf = out / f"{name}.pdf"
    if not pdf.exists():
        req = urllib.request.Request(DS[name], headers={"User-Agent": "Mozilla/5.0"})
        pdf.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    doc = fitz.open(pdf)
    (out / f"{name}.txt").write_text(
        "\n".join(f"=== page {i + 1}\n{p.get_text()}" for i, p in enumerate(doc)),
        encoding="utf-8",
    )
    print(name, doc.page_count, "pages")
