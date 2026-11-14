"""체결 규칙 시험 — 임시 폴더와 가짜 가격으로만 돈다 (실제 장부·네트워크를 건드리지 않는다).

실행: python tests/test_broker.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROKER = ROOT / "broker" / "broker.py"
tmp = Path(tempfile.mkdtemp(prefix="paper_test_"))
shutil.copy(ROOT / "config.json", tmp / "config.json")
(tmp / "data" / "prices").mkdir(parents=True)


def bars(rows):
    return [{"d": d, "o": o, "h": h, "l": l, "c": c} for d, o, h, l, c in rows]


def put(key, market, ccy, rows):
    (tmp / "data" / "prices" / f"{key}.json").write_text(json.dumps(
        {"symbol": key, "market": market, "currency": ccy, "name": key + " 시험", "bars": bars(rows)},
        ensure_ascii=False), encoding="utf-8")


put("AAA", "US", "USD", [("2026-10-30", 99, 101, 98, 100), ("2026-11-02", 100, 104, 99, 102),
                         ("2026-11-03", 103, 105, 101, 104), ("2026-11-04", 96, 97, 88, 90),
                         ("2026-11-05", 91, 95, 90, 94)])
put("000001", "KR", "KRW", [("2026-10-30", 50000, 50500, 49500, 50000), ("2026-11-02", 50000, 51000, 49800, 50500),
                            ("2026-11-03", 50600, 52000, 50400, 51000), ("2026-11-04", 51000, 51500, 50000, 50200),
                            ("2026-11-05", 50200, 50900, 49900, 50800), ("2026-11-06", 50800, 51000, 50500, 50900)])
put("QQQ", "US", "USD", [("2026-10-30", 600, 600, 600, 600), ("2026-11-05", 606, 606, 606, 606)])
put("069500", "KR", "KRW", [("2026-10-30", 80000, 80000, 80000, 80000), ("2026-11-06", 80800, 80800, 80800, 80800)])
put("USDKRW", "FX", "KRW", [("2026-10-30", 1300, 1300, 1300, 1300), ("2026-11-02", 1310, 1310, 1310, 1310),
                            ("2026-11-04", 1320, 1320, 1320, 1320)])


def run(now, *args, ok=True):
    env = {**os.environ, "PAPER_HOME": str(tmp), "PAPER_NOW": now, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(BROKER), *args], env=env, capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode != 0:
        raise SystemExit(f"명령 실패 {args}: {r.stdout}{r.stderr}")
    return r


fails = []


def check(label, cond, detail=""):
    print(("  통과 " if cond else "  실패 ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)


MON = "2026-11-02T10:00:00+09:00"
run(MON, "open")
run(MON, "order", "--ref", "T1", "--symbol", "AAA", "--side", "buy", "--krw", "10000000", "--type", "moc")   # O0001 종가 주문
run(MON, "order", "--ref", "T1", "--symbol", "000001", "--side", "buy", "--qty", "10", "--type", "moc")      # O0002
run(MON, "order", "--ref", "T1", "--symbol", "AAA", "--side", "sell", "--qty", "all",
    "--type", "stop", "--price", "95")                                                                # O0003
run(MON, "order", "--ref", "T1", "--symbol", "000001", "--side", "buy", "--qty", "5",
    "--type", "limit", "--price", "40000", "--valid-days", "2")                                        # O0004
bad = run(MON, "order", "--ref", "T1", "--symbol", "000001", "--side", "buy", "--krw", "900000000", "--type", "moc", ok=False)
check("가진 돈보다 큰 주문은 접수되지 않는다", bad.returncode != 0 and "주문 가능 금액" in bad.stdout + bad.stderr)
run(MON, "order", "--ref", "T1", "--symbol", "000001", "--side", "buy", "--krw", "45000000", "--type", "moc")   # O0005 접수는 되지만 체결 때 현금이 모자란다
bad = run(MON, "order", "--ref", "T1", "--symbol", "ZZZ", "--side", "sell", "--qty", "1", ok=False)
check("보유하지 않은 종목 매도는 접수 단계에서 막힌다", bad.returncode != 0)

run("2026-11-07T09:00:00+09:00", "settle")
st = json.loads(run("2026-11-07T09:00:00+09:00", "build") and (tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8"))
o = {x["id"]: x for x in st["orders"]}

# O0001: 월요일 10시(한국) 주문 → 미국 11-02 종가 102, 환율 1310. 주당 133,620원, 비용 0.1%
r = o["O0001"]["result"]
check("미국 시장가: 주문 뒤 처음 열리는 날 종가", o["O0001"]["status"] == "filled" and r["date"] == "2026-11-02" and r["price"] == 102, str(r))
check("금액 주문: 비용 포함해 살 수 있는 최대 주 수", r["qty"] == 74, str(r["qty"]))          # 10,000,000 / (133,620*1.001) = 74.7
check("원화 계산과 비용", r["gross_krw"] == 74 * 133620 and r["fee_krw"] == round(74 * 133620 * 0.001), str(r))
# O0002: 한국 10시 주문 → 그날 장은 이미 열렸으니 11-03 종가 51,000
r = o["O0002"]["result"]
check("한국 시장가: 개장 뒤 주문은 다음 거래일 종가", r["date"] == "2026-11-03" and r["price"] == 51000, str(r))
# O0003: 손절 95 — 산 날(11-02)은 건너뛰고 11-04 저가 88에 닿음, 시가 96 > 95 이므로 95 에 체결
r = o["O0003"]["result"]
check("손절: 닿은 날 손절가(시가가 더 낮으면 시가)에 전량", o["O0003"]["status"] == "filled" and r["date"] == "2026-11-04"
      and r["price"] == 95 and r["qty"] == 74 and r["fx"] == 1320, str(r))
check("지정가: 닿지 않으면 만료", o["O0004"]["status"] == "expired", o["O0004"]["status"])
check("접수 뒤 다른 체결로 현금이 줄면 체결 단계에서 거부", o["O0005"]["status"] == "rejected" and "현금 부족" in o["O0005"]["result"]["why"], str(o["O0005"]["result"]))

buy = 74 * 133620
sell = 74 * 95 * 1320
cash = 50000000 - (buy + round(buy * 0.001)) - (510000 + 510) + (sell - round(sell * 0.001))
check("현금 잔액", st["summary"]["cash"] == cash, f"{st['summary']['cash']} vs {cash}")
check("보유는 한국 종목 10주뿐", len(st["positions"]) == 1 and st["positions"][0]["qty"] == 10, str(st["positions"]))
check("총자산 = 현금 + 평가액", st["summary"]["total"] == cash + 10 * 50900, str(st["summary"]["total"]))
bench = round(50000000 * (0.5 * (606 * 1320) / (600 * 1310) + 0.5 * 80800 / 80000))   # 기준일(개설일 11-02) 환율 1310
check("비교 기준 계산", st["equity"][-1]["bench"] == bench, f"{st['equity'][-1]['bench']} vs {bench}")
real = (sell - round(sell * 0.001)) - (buy + round(buy * 0.001))
unreal = 10 * 50900 - (510000 + 510)
op = st["order_pnl"]
check("산 주문별 손익: 다 판 주문은 실현 손익, 들고 있는 주문은 미실현 손익",
      op["O0001"]["realized_krw"] == real and op["O0001"]["unrealized_krw"] == 0 and op["O0002"]["unrealized_krw"] == unreal, str(op))
check("주문에 꼬리표가 실려 다닌다", o["O0001"]["ref"] == "T1" and o["O0001"]["fills"][0]["ref"] == "T1")
check("거래소 화면 자료에는 결정·보고가 없다", not any(k in st for k in ("decisions", "reports", "sources", "memos", "interventions")))
check("장부 지문 이상 없음", st["integrity"]["ok"])

led = tmp / "ledger" / "ledger.jsonl"
led.write_text(led.read_text(encoding="utf-8").replace('"krw": 10000000.0', '"krw": 20000000.0'), encoding="utf-8")
check("장부를 손대면 검증이 실패한다", run(MON, "verify", ok=False).returncode != 0)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'전부 통과' if not fails else '실패 ' + str(len(fails)) + '건'}")
sys.exit(1 if fails else 0)
