"""돈의 흐름 시험 — 원화·달러 예수금, 환전, 시장별 비용, 배당, 액면분할·병합, 옛 장부 읽기.
임시 폴더와 가짜 시세로만 돈다 (실제 장부·네트워크를 건드리지 않는다).

실행: python tests/test_money.py
"""
import hashlib
import json
import math
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

# 시험용 요율 — 실제 config.json 의 값이 바뀌어도 이 시험의 기대값은 그대로다 (2026-11-14 에 정한 값과 같다)
FEES = {"KR": {"commission_rate": 0.00015, "exchange_fee_rate": 0.000036396, "sell_tax_rate": 0.002},
        "US": {"commission_rate": 0.0025, "sec_fee_rate": 0.0000206, "sec_fee_from": "2026-04-04",
               "taf_per_share": 0.000195, "taf_max": 9.79},
        "fx_spread_rate": 0.002, "dividend_tax": {"KR": 0.154, "US": 0.15},
        "us_gains_tax": {"rate": 0.22, "deduction_krw": 2500000}}
DAYS = ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10"]


def home(**over):
    h = Path(tempfile.mkdtemp(prefix="paper_money_"))
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg.update({"fees": FEES, "usd_shortfall": "auto"})
    cfg.update(over)
    (h / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return h


def daily(h, key, market, prices, events=None, kind=None):
    """prices: {날짜: 값} 또는 값 하나(모든 날 같은 값)."""
    if not isinstance(prices, dict):
        prices = {d: prices for d in DAYS}
    c = {"symbol": key, "market": market, "currency": "USD" if market == "US" else "KRW", "name": key + " 시험",
         "bars": [{"d": d, "o": v, "h": v, "l": v, "c": v} for d, v in sorted(prices.items())]}
    if events:
        c["events"] = events
    if kind:
        c["kind"] = kind
    p = h / "data" / "prices" / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def fx_minute(h, when, rate):
    t = int(datetime.fromisoformat(when).replace(tzinfo=KST).timestamp())
    d = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    p = h / "data" / "minutes" / "USDKRW" / f"{d}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"step": 60, "src": "시험", "bars": [[t, rate, rate, rate, rate, 0]]}), encoding="utf-8")


def run(h, now, *args, ok=True):
    env = {**os.environ, "PAPER_HOME": str(h), "PAPER_NOW": now, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(BROKER), *args], env=env, capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode != 0:
        raise SystemExit(f"명령 실패 {args}: {r.stdout}{r.stderr}")
    return r


def state(h, now):
    run(h, now, "settle")
    run(h, now, "build")
    return json.loads((h / "docs" / "data" / "state.json").read_text(encoding="utf-8"))


def ledger(h):
    return [json.loads(x) for x in (h / "ledger" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]


fails = []


def check(label, cond, detail=""):
    print(("  통과 " if cond else "  실패 ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)


def order(h, now, *a, ok=True):
    return run(h, now, "order", *a, ok=ok)


# ================= 1막: 환전 주문, 달러로 미국 주식 사기, 한국 주식 비용 =================
print("환전·비용")
h = home()
daily(h, "000010", "KR", 10000, events={"dividends": {"2026-11-05": 500}, "splits": {}}, kind="stock")
daily(h, "000020", "KR", 20000, kind="etf")
daily(h, "000030", "KR", 1000, kind="stock")
daily(h, "DDD", "US", 50, events={"dividends": {"2026-11-04": 1.0}, "splits": {}})
daily(h, "USDKRW", "FX", 1300)
daily(h, "QQQ", "US", 600)
daily(h, "069500", "KR", 80000)
fx_minute(h, "2026-11-02T08:01", 1300)

MON = "2026-11-02T08:00:00+09:00"
run(h, MON, "open")
order(h, MON, "--symbol", "000010", "--side", "buy", "--qty", "100", "--type", "moc")          # O0001
order(h, MON, "--symbol", "000020", "--side", "buy", "--qty", "10", "--type", "moc")           # O0002 (ETF)
oid = order(h, MON, "--symbol", "USD", "--side", "buy", "--krw", "13000000").stdout.strip().splitlines()[-1]   # O0003 환전
check("환전 주문도 마지막 출력 줄이 주문 번호", oid == "O0003", oid)
order(h, MON, "--symbol", "DDD", "--side", "buy", "--qty", "100", "--type", "moc")             # O0004
order(h, MON, "--symbol", "000030", "--side", "buy", "--qty", "15", "--type", "moc")           # O0005
bad = order(h, MON, "--symbol", "USD", "--side", "sell", "--usd", "all", ok=False)
check("달러가 없으면 달러 팔기 주문은 받지 않는다", bad.returncode != 0 and "달러 예수금" in bad.stdout + bad.stderr)
bad = order(h, MON, "--symbol", "USD", "--side", "buy", "--krw", "90000000", ok=False)
check("가진 원화보다 큰 환전은 받지 않는다", bad.returncode != 0 and "주문 가능 금액" in bad.stdout + bad.stderr)
bad = order(h, MON, "--symbol", "USD", "--side", "buy", "--krw", "1000", "--type", "limit", "--price", "1200", ok=False)
check("값을 정해 두는 환전 주문은 없다", bad.returncode != 0)

st = state(h, "2026-11-03T09:00:00+09:00")
o = {x["id"]: x for x in st["orders"]}
r = o["O0003"]["result"]
usd0 = math.floor(13000000 / (1300 * 1.002) * 100) / 100                # 9,980.03달러
krw0 = math.ceil(usd0 * 1300 * 1.002)
check("환전: 주문 뒤 첫 1분 환율(1300)보다 0.2% 비싸게 달러를 산다", o["O0003"]["status"] == "filled" and r["usd"] == usd0 == 9980.03
      and r["mid"] == 1300 and r["rate"] == 1302.6 and r["krw"] == krw0 and r["precision"] == "1분"
      and r["at"] == "2026-11-02T08:01+09:00", str(r))
check("환전 비용 = 바꾼 달러 × 기준 환율 × 0.2%", r["cost_krw"] == round(usd0 * 1300 * 0.002) == r["fee_krw"], str(r["cost_krw"]))
check("환전 주문의 이름·수량이 전표에 실린다", o["O0003"]["name"] == "달러 환전" and o["O0003"]["filled_qty"] == usd0, str(o["O0003"]["name"]))
r = o["O0004"]["result"]
check("달러 예수금이 넉넉하면 자동 환전 없이 달러로 산다", r["delta"] == -5012.5 and r["usd_after"] == round(usd0 - 5012.5, 2)
      and sum(e["type"] == "fx" for e in ledger(h)) == 1, str(r))
s = st["summary"]
krw = 50000000 - krw0 - (1000000 + 186) - (200000 + 37) - (15000 + 2)
check("원화 예수금: 환전과 한국 주식 값·수수료가 빠진다", s["cash_krw"] == krw, f"{s['cash_krw']} vs {krw}")
usd = round(usd0 - 5012.5, 2)                                           # 4,967.53달러
check("달러 예수금과 그 원화 값어치", s["cash_usd"] == usd == 4967.53 and s["cash_usd_krw"] == round(usd * 1300), str(s))
total = krw + round(usd * 1300) + 1000000 + 200000 + 15000 + 100 * 50 * 1300
check("총자산 = 원화 + 달러(그날 환율) + 주식", s["total"] == total and st["equity"][-1]["total"] == total, f"{s['total']} vs {total}")
check("현금 비중은 원화와 달러를 합쳐서", s["cash"] == krw + round(usd * 1300) and s["cash_pct"] == round(s["cash"] / total * 100, 1), str(s["cash_pct"]))

# ================= 2막: 팔 때 세금, ETF 면제, 배당 =================
print("세금·배당")
TUE = "2026-11-03T10:00:00+09:00"
order(h, TUE, "--symbol", "000010", "--side", "sell", "--qty", "40", "--type", "moc")          # O0006 → 11-04 종가 (배당락 전날)
order(h, TUE, "--symbol", "000020", "--side", "sell", "--qty", "10", "--type", "moc")          # O0007 ETF
WED = "2026-11-04T10:00:00+09:00"
order(h, WED, "--symbol", "DDD", "--side", "buy", "--qty", "10", "--type", "moc")              # O0008 배당락일에 산다
order(h, WED, "--symbol", "DDD", "--side", "buy", "--qty", "5", "--type", "limit", "--price", "40")   # O0009 닿지 않는 지정가
st = state(h, "2026-11-06T09:00:00+09:00")
o = {x["id"]: x for x in st["orders"]}
r = o["O0006"]["result"]
check("한국 주식 팔 때: 수수료 + 거래세 0.20%", r["fees"] == {"commission": 74, "tax": 800} and r["delta"] == 400000 - 874, str(r))
r = o["O0007"]["result"]
check("한국 ETF 팔 때: 거래세 없음", r["fees"] == {"commission": 37, "tax": 0} and r["etf"] is True, str(r))
dv = {d["symbol"]: d for d in st["dividends"]}
d = dv.get("000010", {})
check("한국 배당: 배당락 전날까지 들고 있던 60주 × 500원, 15.4% 떼고 원화로", d.get("qty") == 60 and d.get("gross") == 30000
      and d.get("tax") == 4620 and d.get("net") == 25380 and d.get("ccy") == "KRW", str(d))
d = dv.get("DDD", {})
check("미국 배당: 배당락일에 산 10주는 빼고 100주 × 1달러, 15% 떼고 달러로", d.get("qty") == 100 and d.get("gross") == 100
      and d.get("tax") == 15 and d.get("net") == 85 and d.get("ccy") == "USD" and d.get("net_krw") == 85 * 1300, str(d))
s = st["summary"]
check("배당 합계가 화면 자료에 나온다", s["dividends"] == {"count": 2, "gross_krw": 30000 + 130000, "tax_krw": 4620 + 19500,
                                               "net_krw": 25380 + 110500}, str(s["dividends"]))
krw += (400000 - 874) + (200000 - 37) + 25380
usd = round(usd - 501.25 + 85, 2)
check("배당이 예수금에 들어왔다", s["cash_krw"] == krw and s["cash_usd"] == usd, f"{s['cash_krw']} vs {krw}, {s['cash_usd']} vs {usd}")
check("배당은 산 주문별 손익에 따로 적힌다 (뜻이 정해진 세 항목은 그대로)", st["order_pnl"]["O0001"]["dividend_krw"] == 25380
      and st["order_pnl"]["O0001"]["total_krw"] == st["order_pnl"]["O0001"]["realized_krw"] + st["order_pnl"]["O0001"]["unrealized_krw"],
      str(st["order_pnl"]["O0001"]))
texts = " / ".join(f["text"] for f in st["feed"])
check("배당이 '일어난 일'에 사람 말로 나온다", "배당 — 000010 시험 60주" in texts and "예수금으로 들어왔습니다" in texts, texts[:300])
n = len(ledger(h))
state(h, "2026-11-06T10:00:00+09:00")
check("같은 배당을 두 번 받지 않는다", len(ledger(h)) == n)

# ================= 3막: 액면분할·병합 =================
print("분할·병합")
# 11-09 에 DDD 2대1 분할, 000030 10대1 병합. 시세 원천은 분할 뒤 기준으로 지난 값을 전부 고쳐 준다 → 캐시를 그렇게 다시 쓴다.
daily(h, "DDD", "US", {**{d: 25 for d in DAYS}, "2026-11-10": 60},
      events={"dividends": {"2026-11-04": 0.5}, "splits": {"2026-11-09": [2, 1]}})
daily(h, "000030", "KR", 10000, events={"dividends": {}, "splits": {"2026-11-09": [1, 10]}}, kind="stock")
st = state(h, "2026-11-10T09:00:00+09:00")
pos = {p["symbol"]: p for p in st["positions"]}
o = {x["id"]: x for x in st["orders"]}
cost = round((5012.5 + 501.25) * 1300)
check("액면분할: 110주 → 220주, 산 값 총액은 그대로", pos["DDD"]["qty"] == 220 and pos["DDD"]["cost_krw"] == cost
      and pos["DDD"]["avg_cost_krw"] == round(cost / 220), str(pos["DDD"]))
check("분할 뒤 값어치는 새 주식 수 × 새 값(이날 종가 60)", pos["DDD"]["value_krw"] == 220 * 60 * 1300, str(pos["DDD"]["value_krw"]))
check("그 종목에 걸려 있던 주문은 거둔다", o["O0009"]["status"] == "canceled" and "분할" in o["O0009"]["result"]["why"], str(o["O0009"]["status"]))
sp = [e["data"] for e in ledger(h) if e["type"] == "split" and e["data"]["symbol"] == "000030"][0]
check("병합: 15주 → 1주, 1주가 안 되는 0.5주는 돈(5,000원)으로", pos["000030"]["qty"] == 1 and sp["qty_after"] == 1 and sp["cash"] == 5000, str(sp))
krw += 5000
check("자투리 값이 원화 예수금에 들어왔다", st["summary"]["cash_krw"] == krw, f"{st['summary']['cash_krw']} vs {krw}")
eq = {e["d"]: e for e in st["equity"]}
check("자산 곡선: 분할 전 날짜도 고쳐진 시세 × 지금 주식 수로 같은 값어치",
      eq["2026-11-06"]["total"] == krw - 5000 + round(usd * 1300) + 60 * 10000 + 15000 + 220 * 25 * 1300, str(eq["2026-11-06"]))
texts = " / ".join(f["text"] for f in st["feed"])
check("분할·병합이 '일어난 일'에 사람 말로 나온다", "액면분할 — DDD 시험 1주가 2주로" in texts and "주식 병합 — 000030 시험" in texts, texts[:300])
check("지난 배당의 금액이 나중에 바뀌어 보여도 다시 주지 않는다", len(st["dividends"]) == 2)

# ================= 4막: 미국 주식 팔기, 달러를 원화로, 양도세 어림 =================
print("달러 → 원화")
order(h, "2026-11-10T10:00:00+09:00", "--symbol", "DDD", "--side", "sell", "--qty", "all", "--type", "moc")   # O0010 → 11-10 종가 60
inbox = h / "inbox"
inbox.mkdir()
(inbox / "001.json").write_text(json.dumps({"client_id": "fx-1", "action": "order", "ref": "T7", "symbol": "USDKRW",
                                             "side": "sell", "usd": "all"}), encoding="utf-8")
run(h, "2026-11-11T08:00:00+09:00", "ingest")                                                  # O0011 창구로 온 환전 요청
fx_minute(h, "2026-11-11T08:01", 1310)
st = state(h, "2026-11-12T09:00:00+09:00")
o = {x["id"]: x for x in st["orders"]}
r = o["O0010"]["result"]
check("미국 주식 팔기: 수수료 33달러, 매도 제비용 0.33달러(SEC 0.28 + FINRA 0.05)", r["qty"] == 220 and r["fees"] == {"commission": 33.0, "tax": 0.33}
      and r["delta"] == 13166.67, str(r))
usd = round(usd + 13166.67, 2)
r = o["O0011"]["result"]
got = math.floor(usd * 1310 * 0.998 + 1e-6)
check("창구로 온 환전 요청: 달러 전부를 기준 환율(1310)보다 0.2% 싸게 원화로", o["O0011"]["status"] == "filled" and o["O0011"]["client_id"] == "fx-1"
      and r["usd"] == usd and r["krw"] == got and r["cost_krw"] == round(usd * 1310 * 0.002), str(r))
s = st["summary"]
krw += got
check("달러 예수금이 비고 원화로 돌아왔다", s["cash_usd"] == 0 and s["cash_krw"] == krw and s["cash"] == krw, f"{s['cash_krw']} vs {krw}")
check("총자산 = 원화 + 남은 한국 주식", s["total"] == krw + 60 * 10000 + 10000, f"{s} {st['positions']} {st['equity'][-2:]}")
gain = round((13166.67 - 5513.75) * 1300)
check("해외 주식 양도세는 떼지 않고 예상 금액만", s["us_gains"]["realized_krw"] == gain and s["us_gains"]["year"] == "2026"
      and s["us_gains"]["est_tax_krw"] == round((gain - 2500000) * 0.22), str(s["us_gains"]))
fxc = round(usd0 * 1300 * 0.002) + round(usd * 1310 * 0.002)
check("낸 비용 내역: 환전 비용은 두 번의 환전 합", s["costs"]["fx_krw"] == fxc and s["fees_krw"] == sum(s["costs"].values()), str(s["costs"]))
check("장부 지문 이상 없음", st["integrity"]["ok"])
need = {"account", "summary", "positions", "equity", "orders", "order_pnl", "refused", "integrity"}
check("일지가 읽어 가는 항목이 그대로 있다", need <= set(st) and {"total", "pnl_krw", "pnl_pct", "bench_pct", "cash_pct"} <= set(s)
      and {"symbol", "name", "weight", "pnl_pct"} <= set(st["positions"][0])
      and {"id", "name", "side", "status", "filled_qty", "result"} <= set(st["orders"][0]) and "d" in st["equity"][-1])
shutil.rmtree(h, ignore_errors=True)

# ================= 달러가 모자랄 때 거부하도록 정한 경우 =================
print("달러 부족 때 거부 (설정을 바꾼 경우)")
h = home(usd_shortfall="refuse")
daily(h, "DDD", "US", 50)
daily(h, "USDKRW", "FX", 1300)
daily(h, "QQQ", "US", 600)
daily(h, "069500", "KR", 80000)
run(h, MON, "open")
bad = order(h, MON, "--symbol", "DDD", "--side", "buy", "--qty", "10", "--type", "moc", ok=False)
check("달러 예수금이 없으면 미국 주식 매수를 받지 않는다", bad.returncode != 0 and "달러 예수금" in bad.stdout + bad.stderr, bad.stdout + bad.stderr)
order(h, MON, "--symbol", "USD", "--side", "buy", "--usd", "400")                               # O0001 하루 환율로 (1분 환율 없음)
st = state(h, "2026-11-04T09:00:00+09:00")
o = {x["id"]: x for x in st["orders"]}
r = o["O0001"]["result"]
check("1분 환율이 없으면 주문 다음 날 하루 환율의 시작 값으로, 그렇게 적는다", o["O0001"]["status"] == "filled" and r["precision"] == "하루"
      and r["date"] == "2026-11-03" and r["krw"] == math.ceil(400 * 1300 * 1.002), str(r))
order(h, "2026-11-04T10:00:00+09:00", "--symbol", "DDD", "--side", "buy", "--qty", "8", "--type", "moc")   # 수수료까지 401달러 필요, 400달러뿐
st = state(h, "2026-11-06T09:00:00+09:00")
last = sorted(st["orders"], key=lambda x: x["id"])[-1]
check("체결 때 달러가 모자라면 자동 환전 없이 거부", last["status"] == "rejected" and "달러 예수금 부족" in last["result"]["why"]
      and sum(e["type"] == "fx" for e in ledger(h)) == 1, str(last["result"]))
shutil.rmtree(h, ignore_errors=True)

# ================= 옛 장부 읽기 =================
print("옛 장부")
h = home()
cfg = json.loads((h / "config.json").read_text(encoding="utf-8"))
del cfg["fees"], cfg["usd_shortfall"]
cfg["fee_rate"] = 0.001                                    # 옛 설정: 매매마다 0.1% 한 가지
(h / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
daily(h, "AAA", "US", 100)
daily(h, "USDKRW", "FX", 1300)
daily(h, "QQQ", "US", 600)
daily(h, "069500", "KR", 80000)
lines = [json.loads((ROOT / "ledger" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])]   # 실제 장부의 개설 줄 그대로


def old_line(kind, data, ts):
    rec = {"seq": len(lines) + 1, "ts": ts, "type": kind, "data": data, "prev": lines[-1]["hash"]}
    rec["hash"] = hashlib.sha256(json.dumps(rec, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    lines.append(rec)


old_line("order", {"ref": "", "symbol": "AAA", "market": "US", "side": "buy", "type": "moc", "price": None, "session": "regular",
                   "qty": 10, "valid_until": "2026-12-14", "id": "O0001"}, "2026-11-16T10:00:00+09:00")
old_line("fill", {"order": "O0001", "ref": "", "symbol": "AAA", "market": "US", "side": "buy", "date": "2026-11-16", "price": 100.0,
                  "fx": 1300, "qty": 10, "total": 10, "remaining": 0, "at": None, "first_at": None, "last_ts": None,
                  "precision": "하루", "pieces": 1, "triggered": False, "session": "r", "gross_krw": 1300000, "fee_krw": 1300,
                  "cash_delta": -1301300, "cash_after": 48698700}, "2026-11-17T09:00:00+09:00")
(h / "ledger").mkdir()
(h / "ledger" / "ledger.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
check("실제 장부의 개설 줄과 옛 체결 줄의 지문이 맞는다", run(h, "2026-11-17T10:00:00+09:00", "verify", ok=False).returncode == 0)
st = state(h, "2026-11-17T10:00:00+09:00")
s = st["summary"]
check("옛 체결 줄은 원화 한 주머니로 읽는다", s["cash_krw"] == 48698700 and s["cash_usd"] == 0 and s["fees_krw"] == 1300
      and st["positions"][0]["cost_krw"] == 1301300, str(s))
order(h, "2026-11-17T10:00:00+09:00", "--symbol", "AAA", "--side", "sell", "--qty", "all", "--type", "moc")
daily(h, "AAA", "US", {**{d: 100 for d in DAYS}, "2026-11-17": 100})
st = state(h, "2026-11-19T09:00:00+09:00")
r = [x for x in st["orders"] if x["id"] == "O0002"][0]["result"]
check("옛 설정(요율 한 가지)으로도 돈다: 매도 비용 0.1%, 다른 비용 없음", r["fees"] == {"commission": 1.0, "tax": 0} and r["delta"] == 999.0, str(r))
shutil.rmtree(h, ignore_errors=True)

print(f"\n{'전부 통과' if not fails else '실패 ' + str(len(fails)) + '건'}")
sys.exit(1 if fails else 0)
