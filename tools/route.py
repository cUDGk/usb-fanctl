"""freerouting を CLI で回す。python tools/route.py c [max_passes]

freerouting 2.x は Java 25 でビルドされているため、_tools に置いた可搬 JRE を使う。
"""

import subprocess
import sys
from pathlib import Path

JAVA = r"C:\Users\user\KiCadProjects\_tools\jdk-25.0.4.1+1-jre\bin\java.exe"
JAR = r"C:\Users\user\KiCadProjects\vrc-fbt\tools\freerouting.jar"
root = Path(__file__).resolve().parents[1]
kind = sys.argv[1]
passes = sys.argv[2] if len(sys.argv) > 2 else "40"
board = root / f"fanctl_{kind}"
dsn, ses = board / f"fanctl_{kind}.dsn", board / f"fanctl_{kind}.ses"
log = board / "output" / "freerouting.log"
log.parent.mkdir(exist_ok=True)
ses.unlink(missing_ok=True)
with log.open("w", encoding="utf-8") as out:
    proc = subprocess.run(
        [JAVA, "-jar", JAR, "-de", str(dsn), "-do", str(ses), "-mp", passes,
         "--gui.enabled=false", "--api_server.enabled=false"],
        stdout=out, stderr=subprocess.STDOUT, timeout=3600,
    )
print("exit", proc.returncode, "ses" if ses.exists() else "NO SES", log)
