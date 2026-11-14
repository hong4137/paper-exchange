"""실제 1분 시세로 가짜 주문을 체결시켜 화면 확인용 자료(docs/data/demo.json)를 만든다.
임시 폴더에서만 돌고 실제 장부는 건드리지 않는다. 네트워크가 필요하다.
주문 날짜가 아래에 박혀 있다 — 1분 시세는 최근 8일치뿐이라, 오래 지나 다시 만들려면 날짜를 최근 거래일로 고친다.

실행: python tests/make_demo_real.py   → 화면에서 index.html?demo
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="paper_real_"))
shutil.copy(ROOT / "config.json", tmp / "config.json")


def run(now, *a, ok=True):
    env = {**os.environ, "PAPER_HOME": str(tmp), "PYTHONIOENCODING": "utf-8"}
    if now:
        env["PAPER_NOW"] = now
    r = subprocess.run([sys.executable, str(ROOT / "broker" / "broker.py"), *a], env=env, capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    return r.stdout.strip()


run("2026-11-11T18:00:00+09:00", "open")
run("2026-11-12T08:50:00+09:00", "order", "--symbol", "005930", "--side", "buy", "--krw", "5000000")
run("2026-11-12T10:17:20+09:00", "order", "--symbol", "069500", "--side", "buy", "--qty", "30")
run("2026-11-12T21:00:00+09:00", "order", "--symbol", "MU", "--side", "buy", "--krw", "5000000")
run("2026-11-13T00:05:10+09:00", "order", "--symbol", "NET", "--side", "buy", "--qty", "20")
run("2026-11-13T09:30:00+09:00", "order", "--symbol", "005930", "--side", "sell", "--qty", "all", "--type", "stop", "--price", "210000")
run("2026-11-13T09:30:00+09:00", "order", "--symbol", "069500", "--side", "buy", "--qty", "20", "--type", "limit", "--price", "83000")
run("2026-11-13T12:00:00+09:00", "order", "--symbol", "171090", "--side", "buy", "--qty", "350")   # 거래량 한도 시험
run("2026-11-13T06:10:00+09:00", "order", "--symbol", "MU", "--side", "buy", "--qty", "3",
    "--type", "limit", "--price", "775", "--session", "all")            # 미국 장후(시간외 포함 지정가)
run("2026-11-13T16:30:00+09:00", "order", "--symbol", "069500", "--side", "sell", "--qty", "10",
    "--type", "limit", "--price", "83200", "--session", "all")          # 한국 장후(넥스트레이드 애프터마켓)
print(run(None, "update"))
print(run(None, "settle"))
run(None, "build")
st = json.loads((tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8"))
for o in sorted(st["orders"], key=lambda x: x["id"]):
    r = o["result"] or {}
    print(f"\n{o['id']} {o['name']} {o['side']} {o['type']} {o.get('price') or ''} → {o['status']}")
    for f in o.get("fills", []):
        print(f"   {f['first_at']} ~ {f['at']}  {f['qty']}주 @ {f['price']}  조각 {f['pieces']}  {f['precision']}  환율 {f['fx']}  남음 {f['remaining']}")
    if r.get("why"):
        print("   사유:", r["why"])
out = ROOT / "docs" / "data" / "demo.json"
shutil.copy(tmp / "docs" / "data" / "state.json", out)
shutil.rmtree(tmp, ignore_errors=True)
print("만듦:", out)
