"""1분 단위 체결 시험 — 임시 폴더와 가짜 시세로만 돈다.

실행: python tests/test_intraday.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROKER = ROOT / "broker" / "broker.py"
KST = timezone(timedelta(hours=9))
tmp = Path(tempfile.mkdtemp(prefix="paper_intra_"))
shutil.copy(ROOT / "config.json", tmp / "config.json")

# 시험용 요율 — 실제 config.json 의 값이 바뀌어도 이 시험의 기대값은 그대로다 (2026-11-14 에 정한 값과 같다)
FEES = {"KR": {"commission_rate": 0.00015, "exchange_fee_rate": 0.000036396, "sell_tax_rate": 0.002},
        "US": {"commission_rate": 0.0025, "sec_fee_rate": 0.0000206, "sec_fee_from": "2026-04-04",
               "taf_per_share": 0.000195, "taf_max": 9.79},
        "fx_spread_rate": 0.002, "dividend_tax": {"KR": 0.154, "US": 0.15},
        "us_gains_tax": {"rate": 0.22, "deduction_krw": 2500000}}
_cfg = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
_cfg.update({"fees": FEES, "usd_shortfall": "auto"})
(tmp / "config.json").write_text(json.dumps(_cfg, ensure_ascii=False), encoding="utf-8")


def ts(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=KST).timestamp())


def daily(key, market, ccy, rows):
    p = tmp / "data" / "prices" / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"symbol": key, "market": market, "currency": ccy, "name": key + " 시험",
                             "bars": [{"d": d, "o": o, "h": h, "l": l, "c": c} for d, o, h, l, c in rows]},
                            ensure_ascii=False), encoding="utf-8")


def minutes(key, d, rows, step=60):
    p = tmp / "data" / "minutes" / key / f"{d}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"step": step, "src": "시험", "bars": [[ts(r[0]), *r[1:]] for r in rows]}), encoding="utf-8")


# 한국 종목 000002 — 호가 단위 50원이 되도록 값을 잡았다
daily("000002", "KR", "KRW", [("2026-11-09", 10000, 10000, 10000, 10000), ("2026-11-10", 10000, 10100, 9700, 9800),
                              ("2026-11-11", 9600, 9650, 9550, 9600)])
minutes("000002", "2026-11-10", [
    ("2026-11-10T09:00", 10000, 10050, 9950, 10000, 1000),
    ("2026-11-10T09:01", 10000, 10100, 10000, 10100, 50),      # 거래량이 적다 → 5주만
    ("2026-11-10T09:02", 10100, 10100, 10000, 10050, 2000),
    ("2026-11-10T09:03", 10050, 10050, 9850, 9900, 500),       # 지정가 9900 을 지나간다
    ("2026-11-10T09:10", 9850, 9850, 9700, 9750, 300),         # 손절가 9800 에 닿는다
    ("2026-11-10T09:11", 9750, 9800, 9700, 9800, 1000),
])
minutes("000002", "2026-11-11", [("2026-11-11T09:00", 9600, 9650, 9550, 9600, 10000)])
# 하루 시세만 있는 종목
daily("000003", "KR", "KRW", [("2026-11-09", 5000, 5000, 5000, 5000), ("2026-11-10", 5100, 5200, 5050, 5150)])
# 미국 종목 BBB — 11-10 장은 한국 시각 23:30 에 열린다. 1분 환율 1400, 하루 환율 1300
daily("BBB", "US", "USD", [("2026-11-09", 100, 100, 100, 100)])
minutes("BBB", "2026-11-10", [("2026-11-10T23:30", 100, 100.5, 99.5, 100.2, 10000)])
daily("USDKRW", "FX", "KRW", [("2026-11-09", 1300, 1300, 1300, 1300)])
minutes("USDKRW", "2026-11-10", [("2026-11-10T23:29", 1400, 1400, 1400, 1400, 0)])
# 미국 종목 CCC — 장후(한국 06:00~10:00) 봉에는 거래량이 없다
daily("CCC", "US", "USD", [("2026-11-09", 100, 100, 100, 100), ("2026-11-10", 100, 101, 99.5, 100)])
minutes("CCC", "2026-11-10", [
    ("2026-11-10T23:30", 100, 100.5, 99.5, 100.2, 10000, "r"),
    ("2026-11-11T06:31", 100, 100, 98.5, 99, 0, "post"),       # 장후: 지정가 99 를 지나간다
    ("2026-11-11T06:32", 99, 99.2, 98.8, 99, 0, "post"),
    ("2026-11-11T06:33", 97, 97.5, 96.5, 97, 0, "post"),       # 장후 마지막 값 97
])
daily("QQQ", "US", "USD", [("2026-11-09", 600, 600, 600, 600)])
daily("069500", "KR", "KRW", [("2026-11-09", 80000, 80000, 80000, 80000)])


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


run("2026-11-09T18:00:00+09:00", "open")
A = "2026-11-10T09:00:30+09:00"
run("2026-11-10T08:00:00+09:00", "order", "--symbol", "000002", "--side", "buy", "--qty", "10",
    "--type", "limit", "--price", "9900")                                                    # O0001 지정가
run(A, "order", "--symbol", "000002", "--side", "buy", "--qty", "150")       # O0002 시장가
run("2026-11-10T09:05:00+09:00", "order", "--symbol", "000002", "--side", "sell", "--qty", "all",
    "--type", "stop", "--price", "9800")                                                     # O0003 손절
run("2026-11-10T08:30:00+09:00", "order", "--symbol", "000003", "--side", "buy", "--qty", "10")  # O0004 하루 시세
run("2026-11-10T20:00:00+09:00", "order", "--symbol", "BBB", "--side", "buy", "--krw", "1000000")  # O0005 미국
E = "2026-11-11T06:30:00+09:00"
run(E, "order", "--symbol", "CCC", "--side", "buy", "--qty", "30", "--type", "limit", "--price", "99",
    "--session", "all")                                                                        # O0006 시간외 포함
run(E, "order", "--symbol", "CCC", "--side", "buy", "--qty", "5", "--type", "limit", "--price", "99")  # O0007 정규장만
bad = run(E, "order", "--symbol", "CCC", "--side", "buy", "--qty", "1", "--session", "all", ok=False)
check("시간외에는 시장가 주문을 낼 수 없다", bad.returncode != 0 and "지정가" in bad.stdout + bad.stderr)
bad = run(A, "order", "--symbol", "000002", "--side", "buy", "--qty", "1", "--type", "limit", "--price", "9925", ok=False)
check("호가 단위에 안 맞는 가격은 접수되지 않는다", bad.returncode != 0 and "호가 단위" in bad.stdout + bad.stderr, bad.stdout + bad.stderr)
bad = run(A, "order", "--symbol", "000002", "--side", "buy", "--qty", "1", "--type", "limit", "--price", "5000", ok=False)
check("상·하한가 밖의 가격은 접수되지 않는다", bad.returncode != 0 and "상·하한가" in bad.stdout + bad.stderr, bad.stdout + bad.stderr)

N = "2026-11-12T09:00:00+09:00"
run(N, "settle")
run(N, "build")
st = json.loads((tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8"))
o = {x["id"]: x for x in st["orders"]}

r = o["O0002"]["result"]
avg = round((5 * 10050 + 145 * 10100) / 150, 4)
check("시장가: 주문 뒤 첫 1분의 시가 + 호가 차이, 주문 전 1분(09:00)은 쓰지 않는다",
      o["O0002"]["status"] == "filled" and r["first_at"] == "2026-11-10T09:01+09:00", str(r))
check("거래량 한도: 5주는 09:01, 나머지 145주는 09:02 에", r["pieces"] == 2 and r["price"] == avg and r["at"] == "2026-11-10T09:02+09:00", str(r))
check("1분 시세로 체결했다고 적힌다", r["precision"] == "1분", r["precision"])
r = o["O0001"]["result"]
check("지정가: 값이 지나간 1분(09:03)에 지정가로", o["O0001"]["status"] == "filled" and r["price"] == 9900 and r["at"] == "2026-11-10T09:03+09:00", str(r))
r = o["O0003"]
f1, f2 = r["fills"][0], r["fills"][1] if len(r["fills"]) > 1 else None
check("손절: 닿은 1분(09:10)부터 팔고, 거래량이 모자라 첫날은 130주만",
      f1["qty"] == 130 and f1["first_at"] == "2026-11-10T09:10+09:00" and f1["remaining"] == 30 and f1["triggered"], str(f1))
check("손절 첫 조각은 손절가에서 호가 차이만큼 불리하게(9750), 다음 1분은 시장가(9700)",
      f1["price"] == round((30 * 9750 + 100 * 9700) / 130, 4), str(f1["price"]))
check("남은 30주는 다음 거래일 첫 1분에 이어서", f2 and f2["qty"] == 30 and f2["date"] == "2026-11-11" and f2["price"] == 9550
      and r["status"] == "filled", str(f2))
r = o["O0004"]["result"]
check("1분 시세가 없는 날: 하루 시세의 시가로 어림하고 그렇게 적는다", r["price"] == 5100 and r["precision"] == "하루" and r["date"] == "2026-11-10", str(r))
r = o["O0005"]["result"]
check("미국 시장가: 개장 첫 1분(한국 23:30), 그 시각 1분 환율(1400)로", r["price"] == 100.1 and r["fx"] == 1400 and r["qty"] == 7
      and r["at"] == "2026-11-10T23:30+09:00", str(r))
r = o["O0006"]["result"]
cap = int(3000000 / (99 * 1400))                       # 거래량 없는 시간외 봉: 1분에 300만 원어치까지 = 21주
check("시간외 포함 지정가: 장후 1분(06:31)에 체결되고 '장후'로 적힌다",
      o["O0006"]["status"] == "filled" and r["price"] == 99 and r["first_at"] == "2026-11-11T06:31+09:00"
      and o["O0006"]["fills"][0]["session"] == "post", str(r))
check("시간외 한도: 첫 1분에 21주, 다음 1분에 나머지 9주", cap == 21 and r["pieces"] == 2 and r["at"] == "2026-11-11T06:32+09:00", str(r))
check("정규장만인 지정가는 장후에 체결되지 않는다", o["O0007"]["status"] == "pending", o["O0007"]["status"])
ccc = [p for p in st["positions"] if p["symbol"] == "CCC"][0]
check("보유 종목에 시간외 가격이 따로 붙는다 (장후 97, 종가 100 대비 -3%)",
      ccc["ext"] and ccc["ext"]["price"] == 97 and ccc["ext"]["session"] == "post" and ccc["ext"]["chg_pct"] == -3.0
      and ccc["price"] == 100, str(ccc.get("ext")))
check("총자산은 정규장 종가로, 시간외 변동은 따로", st["summary"]["ext_delta_krw"] == round(30 * 97 * 1400) - round(30 * 100 * 1300),
      str(st["summary"]["ext_delta_krw"]))
check("보유: 000002 는 다 팔렸고 000003·BBB·CCC", sorted(p["symbol"] for p in st["positions"]) == ["000003", "BBB", "CCC"], str([p["symbol"] for p in st["positions"]]))
krw, usd = 50000000, 0.0
for x in st["orders"]:
    for f in x.get("fills", []):
        if f["ccy"] == "USD":
            usd += f["delta"]
        else:
            krw += f["delta"]
led = [json.loads(l) for l in (tmp / "ledger" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
for e in led:
    if e["type"] == "fx":                                  # 미국 주식을 살 때 모자란 달러를 자동 환전한 줄
        krw -= e["data"]["krw"]
        usd += e["data"]["usd"]
check("원화 예수금 = 시작 금액 + 한국 체결 + 환전으로 나간 원화", st["summary"]["cash_krw"] == krw, f"{st['summary']['cash_krw']} vs {krw}")
check("달러 예수금 = 환전으로 들어온 달러 - 미국 주식 산 값 (남는 것 없음)", abs(usd) < 0.005 and st["summary"]["cash_usd"] == 0, f"{usd}")
check("자동 환전은 달러가 모자랐던 미국 매수 체결마다 한 번 (BBB, CCC)", sum(e["type"] == "fx" for e in led) == 2, str(sum(e["type"] == "fx" for e in led)))
check("장부 지문 이상 없음", st["integrity"]["ok"])

# 정기 실행이 늦었고 그 실행에서 마지막 거래일 시세를 못 받았을 때 — 종가 주문을 만료시키지 않고 기다린다 (2026-11-17 선수 질문)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "broker"))
import matching as _mt  # noqa: E402
_o = {"id": "X1", "market": "US", "symbol": "QQQ", "side": "buy", "type": "moc", "qty": 1, "ts": "2026-11-16T10:00:00+09:00",
      "valid_until": "2026-11-17", "filled_qty": 0}
_bars = [{"d": "2026-11-13", "o": 600, "h": 600, "l": 600, "c": 600}]
_ctx = lambda bars, today: {"daily": {"bars": bars}, "minutes": lambda d: None, "minute_dates": [], "held": 0, "pending_buy": False,
                            "last_buy_ts": None, "last_buy_date": None, "size_fn": lambda *x, **k: 10**9, "cfg": {}, "today": today}
check("마지막 거래일 시세가 아직 없으면 기한이 지나도 만료하지 않는다", _mt.next_event(_o, _ctx(_bars, "2026-11-18")) is None)
_ev = _mt.next_event(_o, _ctx(_bars + [{"d": "2026-11-16", "o": 610, "h": 615, "l": 605, "c": 612}], "2026-11-18"))
check("그 시세가 들어오면 늦게라도 그날 종가로 체결된다", bool(_ev) and _ev[0] == "fill", str(_ev)[:160])
_two = _bars + [{"d": "2026-11-16", "o": 610, "h": 615, "l": 605, "c": 612}]
_lim = {**_o, "type": "limit", "price": 500}
check("미국 11-17 거래일(서울 11-17 밤에 열림)도 유효기간 안이라, 그 시세가 오기 전에는 만료하지 않는다", _mt.next_event(_lim, _ctx(_two, "2026-11-18")) is None)
_ev = _mt.next_event(_lim, _ctx(_two + [{"d": "2026-11-17", "o": 612, "h": 620, "l": 608, "c": 615}], "2026-11-18"))
check("마지막 거래일까지 보고도 안 맞으면 그때 만료한다", bool(_ev) and _ev[0] == "expire", str(_ev))

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'전부 통과' if not fails else '실패 ' + str(len(fails)) + '건'}")
sys.exit(1 if fails else 0)
