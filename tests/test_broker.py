"""체결 규칙 시험 — 임시 폴더와 가짜 가격으로만 돈다 (실제 장부·네트워크를 건드리지 않는다).

실행: python tests/test_broker.py
"""
import json
import math
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

# 시험용 요율 — 실제 config.json 의 값이 바뀌어도 이 시험의 기대값은 그대로다 (2026-11-14 에 정한 값과 같다)
FEES = {"KR": {"commission_rate": 0.00015, "exchange_fee_rate": 0.000036396, "sell_tax_rate": 0.002},
        "US": {"commission_rate": 0.0025, "sec_fee_rate": 0.0000206, "sec_fee_from": "2026-04-04",
               "taf_per_share": 0.000195, "taf_max": 9.79},
        "fx_spread_rate": 0.002, "dividend_tax": {"KR": 0.154, "US": 0.15},
        "us_gains_tax": {"rate": 0.22, "deduction_krw": 2500000}}
_cfg = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
_cfg.update({"fees": FEES, "usd_shortfall": "auto"})
(tmp / "config.json").write_text(json.dumps(_cfg, ensure_ascii=False), encoding="utf-8")


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

# O0001: 월요일 10시(한국) 주문 → 미국 11-02 종가 102, 환율 1310. 달러로 산다: 74주 7,548달러 + 수수료 0.25% 18.87달러.
# 달러 예수금이 없으므로 7,566.87달러를 자동 환전(기준 환율보다 0.2% 비싸게)한다.
r = o["O0001"]["result"]
check("미국 시장가: 주문 뒤 처음 열리는 날 종가", o["O0001"]["status"] == "filled" and r["date"] == "2026-11-02" and r["price"] == 102, str(r))
check("금액 주문: 비용 포함해 살 수 있는 최대 주 수", r["qty"] == 74, str(r["qty"]))          # 10,000,000 / (133,620*1.002*1.0025) = 74.5
check("미국 주식은 달러로 계산하고 수수료 0.25%", r["ccy"] == "USD" and r["gross"] == 7548 and r["fees"] == {"commission": 18.87, "tax": 0}
      and r["delta"] == -7566.87 and r["gross_krw"] == 74 * 133620 and r["fee_krw"] == round(18.87 * 1310), str(r))
fx_krw = math.ceil(7566.87 * 1310 * 1.002)
auto = [f for f in st["feed"] if f["type"] == "fx"]
check("달러가 모자라면 모자란 만큼만 자동 환전하고 장부에 따로 남는다", len(auto) == 1 and "자동 환전" in auto[0]["text"]
      and f"{fx_krw:,}원" in auto[0]["text"] and "7,566.87달러" in auto[0]["text"], str(auto))
# O0002: 한국 10시 주문 → 그날 장은 이미 열렸으니 11-03 종가 51,000
r = o["O0002"]["result"]
check("한국 시장가: 개장 뒤 주문은 다음 거래일 종가", r["date"] == "2026-11-03" and r["price"] == 51000, str(r))
check("한국 주식 살 때: 수수료 0.015% + 거래소·예탁원 비용, 세금 없음", r["fees"] == {"commission": 95, "tax": 0} and r["delta"] == -510095, str(r))
# O0003: 손절 95 — 산 날(11-02)은 건너뛰고 11-04 저가 88에 닿음, 시가 96 > 95 이므로 95 에 체결
r = o["O0003"]["result"]
check("손절: 닿은 날 손절가(시가가 더 낮으면 시가)에 전량", o["O0003"]["status"] == "filled" and r["date"] == "2026-11-04"
      and r["price"] == 95 and r["qty"] == 74 and r["fx"] == 1320, str(r))
check("지정가: 닿지 않으면 만료", o["O0004"]["status"] == "expired", o["O0004"]["status"])
check("접수 뒤 다른 체결로 현금이 줄면 체결 단계에서 거부", o["O0005"]["status"] == "rejected" and "현금 부족" in o["O0005"]["result"]["why"], str(o["O0005"]["result"]))

# 판 돈은 달러로 남는다: 7,030 - 수수료 17.58 - 매도 제비용(SEC 0.15 + FINRA 0.02) = 7,012.25달러
check("미국 주식 팔 때: 수수료와 매도 제비용을 달러로 뗀다", r["fees"] == {"commission": 17.58, "tax": 0.17} and r["delta"] == 7012.25, str(r))
s = st["summary"]
krw = 50000000 - fx_krw - 510095
check("원화·달러 예수금이 따로 선다", s["cash_krw"] == krw and s["cash_usd"] == 7012.25 and s["cash_usd_krw"] == round(7012.25 * 1320), str(s))
cash = round(krw + 7012.25 * 1320)                        # 달러는 마지막 환율(1320)로 원화 환산
check("현금 잔액 (원화 + 달러의 원화 값어치)", s["cash"] == cash, f"{s['cash']} vs {cash}")
check("낸 비용이 수수료·세금·환전으로 나뉜다", s["costs"] == {"commission_krw": round(18.87 * 1310 + 95 + 17.58 * 1320),
      "tax_krw": round(0.17 * 1320), "fx_krw": round(7566.87 * 1310 * 0.002)} and s["fees_krw"] == sum(s["costs"].values()), str(s["costs"]))
check("보유는 한국 종목 10주뿐", len(st["positions"]) == 1 and st["positions"][0]["qty"] == 10, str(st["positions"]))
check("총자산 = 현금 + 평가액", st["summary"]["total"] == cash + 10 * 50900, str(st["summary"]["total"]))
bench = round(50000000 * (0.5 * (606 * 1320) / (600 * 1310) + 0.5 * 80800 / 80000))   # 기준일(개설일 11-02) 환율 1310
check("비교 기준 계산", st["equity"][-1]["bench"] == bench, f"{st['equity'][-1]['bench']} vs {bench}")
real = round(7012.25 * 1320 - 7566.87 * 1310)            # 판 돈과 산 값을 각각 그때 환율로 원화 환산
unreal = 10 * 50900 - 510095
op = st["order_pnl"]
check("산 주문별 손익: 다 판 주문은 실현 손익, 들고 있는 주문은 미실현 손익",
      op["O0001"]["realized_krw"] == real and op["O0001"]["unrealized_krw"] == 0 and op["O0002"]["unrealized_krw"] == unreal, str(op))
check("주문에 꼬리표가 실려 다닌다", o["O0001"]["ref"] == "T1" and o["O0001"]["fills"][0]["ref"] == "T1")
check("거래소 화면 자료에는 결정·보고가 없다", not any(k in st for k in ("decisions", "reports", "sources", "memos", "interventions")))
check("장부 지문 이상 없음", st["integrity"]["ok"])

# 주문 창구: 요청 파일을 접수하고, 안 받는 것도 사유와 함께 남기고, 같은 요청은 두 번 받지 않는다
inbox = tmp / "inbox"
inbox.mkdir()
SAT = "2026-11-07T10:00:00+09:00"
(inbox / "001-a.json").write_text(json.dumps({"client_id": "c-a", "action": "order", "ref": "T9", "symbol": "000001",
                                               "side": "buy", "qty": 3, "type": "moc", "requested_at": "2026-11-07T09:59:00+09:00"}), encoding="utf-8")
(inbox / "002-b.json").write_text(json.dumps({"client_id": "c-b", "symbol": "ZZZ", "side": "sell", "qty": 1}), encoding="utf-8")
(inbox / "003-c.json").write_text("{깨진 파일", encoding="utf-8")
out = run(SAT, "ingest").stdout
st3 = json.loads((tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8")) if run(SAT, "build") else None
new = [x for x in st3["orders"] if x.get("client_id") == "c-a"]
check("창구로 온 주문이 접수되고 요청 번호가 따라간다", len(new) == 1 and new[0]["ref"] == "T9" and new[0]["ts"].startswith("2026-11-07T10:00"), out)
why = {r["client_id"]: r["why"] for r in st3["refused"]}
check("받지 않은 요청은 사유와 함께 장부에 남는다", "보유하고 있지 않습니다" in why.get("c-b", "") and "읽을 수 없습니다" in why.get("003-c", ""), str(why))
check("처리한 요청 파일은 창구에서 치운다", not list(inbox.glob("*.json")))
(inbox / "004-again.json").write_text(json.dumps({"client_id": "c-a", "symbol": "000001", "side": "buy", "qty": 3, "type": "moc"}), encoding="utf-8")
(inbox / "005-cancel.json").write_text(json.dumps({"client_id": "c-x", "action": "cancel", "order": new[0]["id"], "why": "시험 취소"}), encoding="utf-8")
run(SAT, "ingest")
st3 = json.loads((tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8")) if run(SAT, "build") else None
again = [x for x in st3["orders"] if x.get("client_id") == "c-a"]
check("같은 요청은 두 번 접수되지 않는다", len(again) == 1)
check("창구로 온 취소 요청이 처리된다", again[0]["status"] == "canceled" and again[0]["result"]["why"] == "시험 취소", str(again[0]["status"]))

led = tmp / "ledger" / "ledger.jsonl"
led.write_text(led.read_text(encoding="utf-8").replace('"krw": 10000000.0', '"krw": 20000000.0'), encoding="utf-8")
check("장부를 손대면 검증이 실패한다", run(MON, "verify", ok=False).returncode != 0)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'전부 통과' if not fails else '실패 ' + str(len(fails)) + '건'}")
sys.exit(1 if fails else 0)
