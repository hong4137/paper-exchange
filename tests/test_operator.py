"""운용자(크론으로 혼자 도는 일지 도구)를 위한 것 시험 — 임시 폴더·가짜 시세, 원천에 묻지 않는다(PAPER_OFFLINE).

종목 확인과 이름 · 장이 열리는 때(휴장일·서머타임·조기 폐장) · 다음 정기 실행 · 주문마다 가장 빠른 체결 시각 ·
보내지 않고 검사(check) · 주문 전에 묻는 값(quote, state.json quotes) · 값 조건 지켜보기(watch).
실행: python tests/test_operator.py
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
sys.path.insert(0, str(ROOT / "broker"))
import markets as mk  # noqa: E402

KST = timezone(timedelta(hours=9))
tmp = Path(tempfile.mkdtemp(prefix="paper_oper_"))
shutil.copy(ROOT / "config.json", tmp / "config.json")
fails = []


def check(label, cond, detail=""):
    print(("  통과 " if cond else "  실패 ") + label + ("" if cond else f" — {detail}"))
    if not cond:
        fails.append(label)


def ts(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=KST).timestamp())


def daily(key, market, ccy, rows, name=None):
    p = tmp / "data" / "prices" / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"symbol": key, "market": market, "currency": ccy, "name": name or key + " 시험",
                             "bars": [{"d": d, "o": c, "h": c, "l": c, "c": c} for d, c in rows]}, ensure_ascii=False), encoding="utf-8")


def minutes(key, d, rows):
    p = tmp / "data" / "minutes" / key / f"{d}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"step": 60, "src": "시험", "bars": [[ts(r[0]), *r[1:]] for r in rows]}), encoding="utf-8")


def run(now, *args, ok=True):
    e = {**os.environ, "PAPER_HOME": str(tmp), "PAPER_NOW": now, "PAPER_OFFLINE": "1", "PYTHONIOENCODING": "utf-8", "GITHUB_ACTIONS": ""}
    r = subprocess.run([sys.executable, str(BROKER), *args], env=e, capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode != 0:
        raise SystemExit(f"명령 실패 {args}: {r.stdout}{r.stderr}")
    return r


def ledger():
    return [json.loads(x) for x in (tmp / "ledger" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]


def state():
    return json.loads((tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8"))


def ingest(now, reqs):
    box = tmp / "inbox"
    box.mkdir(exist_ok=True)
    for i, r in enumerate(reqs):
        (box / f"{now[-5:].replace(':', '')}-{i}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    out = run(now, "ingest").stdout
    run(now, "build")
    return out


K = lambda s: datetime.fromisoformat(s).replace(tzinfo=KST)

print("장이 열리는 때 (markets.py)")
st = mk.status("KR", K("2026-11-15T17:30"))
check("일요일 한국: 닫힘, 다음 개장 월 09:00", st["state"] == "closed" and st["next_open"] == "2026-11-16T09:00+09:00", st)
check("한국 장전·정규장·장후", [mk.status("KR", K(x))["state"] for x in ("2026-11-16T08:10", "2026-11-16T10:00", "2026-11-16T16:00", "2026-11-16T20:30")]
      == ["pre", "r", "post", "closed"])
check("한국 휴장일(추석·연말)을 건너뛴다", mk.status("KR", K("2026-09-23T16:00"))["next_open"] == "2026-09-28T09:00+09:00"
      and mk.status("KR", K("2026-12-30T16:00"))["next_open"] == "2027-01-04T09:00+09:00")
check("미국 겨울: 한국 23:30 개장·06:00 폐장", mk.status("US", K("2026-11-16T12:00"))["next_open"] == "2026-11-16T23:30+09:00"
      and mk.status("US", K("2026-11-16T23:40"))["next_close"] == "2026-11-17T06:00+09:00")
check("미국 서머타임: 한국 22:30 개장 (3월 둘째 일요일부터)", mk.status("US", K("2026-03-09T12:00"))["next_open"] == "2026-03-09T22:30+09:00"
      and mk.status("US", K("2026-03-06T12:00"))["next_open"] == "2026-03-06T23:30+09:00")
check("미국 추수감사절 휴장, 다음 날 13:00 조기 폐장", mk.status("US", K("2026-11-26T12:00"))["next_open"] == "2026-11-27T23:30+09:00"
      and mk.status("US", K("2026-11-27T23:40"))["next_close"] == "2026-11-28T03:00+09:00")
check("환율: 주말 닫힘, 월 07:00(한국) 다시 열림", mk.status("FX", K("2026-11-15T12:00"))["next_open"] == "2026-11-16T07:00+09:00"
      and mk.status("FX", K("2026-11-16T12:00"))["state"] == "r")
check("표 밖의 해는 알린다", mk.status("KR", K("2029-03-02T12:00"))["calendar_ok"] is False and mk.status("KR", K("2027-03-02T12:00"))["calendar_ok"])
check("다음 정기 실행: 매시 7분", mk.next_cron(K("2026-11-15T17:19")).isoformat() == "2026-11-15T18:07:00+09:00"
      and mk.next_cron(K("2026-11-15T17:05")).isoformat() == "2026-11-15T17:07:00+09:00")
ef = lambda o, t: mk.earliest_fill(o, K(t)).isoformat(timespec="minutes")
check("가장 빠른 체결: 시장가는 다음 정규장의 첫 1분, 장중이면 다음 1분", ef({"market": "KR", "type": "market"}, "2026-11-15T17:19") == "2026-11-16T09:00+09:00"
      and ef({"market": "KR", "type": "market"}, "2026-11-16T10:00:30+09:00") == "2026-11-16T10:01+09:00")
check("시간외 포함 지정가는 장전부터, 종가 주문은 폐장 때", ef({"market": "KR", "type": "limit", "session": "all"}, "2026-11-15T17:19") == "2026-11-16T08:00+09:00"
      and ef({"market": "US", "type": "moc"}, "2026-11-15T17:19") == "2026-11-17T06:00+09:00")

print("종목 확인과 이름")
daily("005930", "KR", "KRW", [("2026-11-12", 100000), ("2026-11-13", 100000)], name="삼성전자")
minutes("005930", "2026-11-13", [("2026-11-13T09:00", 100000, 100500, 99500, 100000, 1000, "r"),
                                 ("2026-11-13T09:01", 100000, 101000, 100000, 100500, 1000, "r"),
                                 ("2026-11-13T16:00", 100500, 100500, 100000, 101000, 100, "post")])
daily("USDKRW", "FX", "KRW", [("2026-11-13", 1400)])
daily("SPY", "US", "USD", [("2026-11-13", 600)])
daily("069500", "KR", "KRW", [("2026-11-13", 50000)])
SAT = "2026-11-14T10:00:00+09:00"
run(SAT, "open")
out = ingest(SAT, [{"client_id": "x1", "symbol": "005930", "side": "buy", "qty": 1, "ref": "D1"},
                   {"client_id": "x2", "symbol": "030531", "side": "buy", "qty": 1, "ref": "D2"}])
s = state()
o1 = next(o for o in s["orders"] if o.get("client_id") == "x1")
why = {r["client_id"]: r["why"] for r in s["refused"]}
check("접수된 주문에는 종목 이름이 붙는다", o1["name"] == "삼성전자" and ledger()[-2]["data"].get("name") == "삼성전자", o1)
check("시세를 받을 수 없는 번호는 받지 않고 사유를 남긴다", "시세를 받을 수 없습니다" in why.get("x2", ""), why)

print("state.json 에 더한 것")
check("시장 상태 (토요일: 한국·미국 닫힘)", s["markets"]["KR"]["state"] == "closed" and s["markets"]["KR"]["next_open"] == "2026-11-16T09:00+09:00"
      and s["markets"]["US"]["state"] == "closed" and set(s["markets"]) == {"KR", "US", "FX"}, s["markets"])
check("다음 정기 실행 예정 시각", s["next_run"]["exchange"] == "2026-11-14T10:07+09:00", s["next_run"])
check("대기 주문마다 가장 빠른 체결 시각", o1["earliest_fill"] == "2026-11-16T09:00+09:00", o1)
q = s["quotes"].get("005930") or {}
check("대기 종목의 값: 종가·마지막 1분 값(장후)·호가 단위·상하한가", q.get("close") == 100000 and q.get("close_date") == "2026-11-13"
      and q["last"]["price"] == 101000 and q["last"]["session"] == "post" and q["last"]["session_label"] == "장후"
      and q.get("tick") == 500 and q.get("limit_up") == 130000 and q.get("limit_down") == 70000, q)

print("보내지 않고 검사 (check)")
n = len(ledger())
r = run(SAT, "check", "--json", json.dumps({"symbol": "005930", "side": "buy", "qty": 2}), ok=False)
j = json.loads(r.stdout.strip().splitlines()[-1])
check("받을 수 있는 주문: 끝 값 0, 접수될 내용과 가장 빠른 체결 시각", r.returncode == 0 and j["ok"] and j["would"]["name"] == "삼성전자"
      and j["earliest_fill"] == "2026-11-16T09:00+09:00", r.stdout + r.stderr)
r2 = run(SAT, "check", "--symbol", "005930", "--side", "buy", "--type", "limit", "--price", "100100", "--qty", "1", ok=False)
r3 = run(SAT, "check", "--json", json.dumps({"symbol": "005930", "side": "buy", "qty": 1000}), ok=False)
r4 = run(SAT, "check", "--json", json.dumps({"symbol": "999999", "side": "buy", "qty": 1}), ok=False)
r5 = run(SAT, "check", "--json", json.dumps({"action": "cancel", "order": "O0009"}), ok=False)
r6 = run(SAT, "check", "--json", json.dumps({"action": "cancel", "order": o1["id"]}), ok=False)
check("받지 않을 주문: 끝 값 3 과 사유 (호가 단위·돈·종목·취소)", r2.returncode == 3 and "호가 단위" in r2.stdout and r3.returncode == 3 and "모자랍니다" in r3.stdout
      and r4.returncode == 3 and "시세를 받을 수 없습니다" in r4.stdout and r5.returncode == 3 and r6.returncode == 0, r2.stdout + r3.stdout + r4.stdout + r5.stdout)
check("검사는 장부에 아무것도 쓰지 않는다", len(ledger()) == n)
r7 = run(SAT, "check", "--json", json.dumps({"client_id": "x1", "symbol": "005930", "side": "buy", "qty": 1}), ok=False)
check("이미 처리한 요청 번호는 미리 알려 준다", r7.returncode == 3 and "이미 처리한" in r7.stdout, r7.stdout)

print("주문 전에 묻는 값 (quote)")
r = run(SAT, "quote", "--symbol", "005930", "--krw", "1000000", ok=False)
j = json.loads(r.stdout.strip().splitlines()[-1])
check("호가 단위·상하한가·금액이면 몇 주", r.returncode == 0 and j["tick"] == 500 and j["limit_up"] == 130000
      and j["shares_for"]["qty"] == 9 and j["shares_for"]["price"] == 101000, r.stdout)
r = run(SAT, "quote", "--symbol", "999999", ok=False)
check("모르는 종목은 끝 값 3", r.returncode == 3 and '"ok": false' in r.stdout, r.stdout)
r = run(SAT, "quote", "--symbol", "SPY", "--usd", "1300", ok=False)
j = json.loads(r.stdout.strip().splitlines()[-1])
check("미국: 호가 단위 0.01, 달러 금액이면 몇 주", j["tick"] == 0.01 and j["shares_for"]["qty"] == 2 and j["fx"] == 1400, r.stdout)

print("값 조건 지켜보기 (watch)")
out = ingest(SAT, [{"client_id": "w1", "action": "watch", "symbol": "005930", "when": "close_below", "value": 95000, "ref": "D1"},
                   {"client_id": "w2", "action": "watch", "symbol": "005930", "when": "price_above", "value": 102000, "ref": "D1"},
                   {"client_id": "w3", "action": "watch", "symbol": "005930", "when": "sometime", "value": 1},
                   {"client_id": "w4", "action": "watch", "symbol": "777777", "when": "close_above", "value": 1}])
s = state()
ws = {w["client_id"]: w for w in s["watches"]}
why = {r["client_id"]: r["why"] for r in s["refused"]}
check("지켜보기 등록: 번호·꼬리표·지켜보는 중", ws["w1"]["id"] == "W0001" and ws["w1"]["status"] == "watching" and ws["w1"]["ref"] == "D1"
      and ws["w1"]["name"] == "삼성전자" and "95,000" in ws["w1"]["text"], ws)
check("이상한 조건·모르는 종목은 받지 않는다", "close_below" in why.get("w3", "") and "시세를 받을 수 없습니다" in why.get("w4", ""), why)
check("등록 전의 시세로는 닿지 않는다", not s["watch_hits"])
# 월요일: 장중에 102,500 을 찍고, 종가는 94,000
minutes("005930", "2026-11-16", [("2026-11-16T09:00", 100000, 100000, 99000, 99500, 1000, "r"),
                                 ("2026-11-16T09:05", 99500, 102500, 99500, 102000, 1000, "r"),
                                 ("2026-11-16T15:30", 94000, 94000, 94000, 94000, 1000, "r")])
daily("005930", "KR", "KRW", [("2026-11-12", 100000), ("2026-11-13", 100000), ("2026-11-16", 94000)], name="삼성전자")
run("2026-11-16T16:10:00+09:00", "build")
s = state()
hits = {w["id"]: w for w in s["watch_hits"]}
check("1분 값 조건: 처음 닿은 1분과 그 값", hits.get("W0002", {}).get("hit") == {"at": "2026-11-16T09:05+09:00", "price": 102500, "date": "2026-11-16"}, hits)
check("종가 조건: 그날 폐장 시각과 종가", hits.get("W0001", {}).get("hit") == {"at": "2026-11-16T15:30+09:00", "price": 94000, "date": "2026-11-16"}, hits)
check("지켜보는 종목도 값 목록에 있다", "005930" in s["quotes"])
out = ingest("2026-11-16T16:20:00+09:00", [{"client_id": "u1", "action": "unwatch", "watch": "W0001", "why": "다 봤다"},
                                     {"client_id": "u2", "action": "unwatch", "watch": "W0001"}])
s = state()
w1 = next(w for w in s["watches"] if w["id"] == "W0001")
why = {r["client_id"]: r["why"] for r in s["refused"]}
check("거둔 지켜보기는 removed, 두 번 거둘 수 없다", w1["status"] == "removed" and "거둘 수 없는" in why.get("u2", ""), (w1, why))
check("흐름(feed)에 지켜보기 등록·거둠이 남는다", any(f["type"] == "watch" for f in s["feed"]) and any(f["type"] == "unwatch" for f in s["feed"]))
run("2027-03-01T10:00:00+09:00", "build")
check("기한이 지나면 expired", next(w for w in state()["watches"] if w["id"] == "W0002")["status"] == "hit"
      and all(w["status"] in ("hit", "removed", "expired") for w in state()["watches"]))
check("장부 지문 이상 없음", run("2027-03-01T10:00:00+09:00", "verify").returncode == 0)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'전부 통과' if not fails else '실패 ' + str(len(fails)) + '건'}")
sys.exit(1 if fails else 0)
