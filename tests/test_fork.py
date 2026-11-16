"""계좌 분기(복제)와 형제 가리기 시험 — 임시 폴더·가짜 시세, 원천에 묻지 않는다(PAPER_OFFLINE).

분기 요청(논거 글) → 주인 승인 → 다음 정기 실행에서 체결 계산 뒤 갈라짐. 복제본은 원본 장부의 지금까지 줄을 그대로 이어받는다.
에이전트가 자기 계좌만 받아 간 폴더(명단 없이 accounts/{이름표}/)에서 읽기 명령이 되는지도 본다.
실행: python tests/test_fork.py
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
tmp = Path(tempfile.mkdtemp(prefix="paper_fork_"))
cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
cfg["benchmark"] = [{"symbol": "069500", "weight": 1.0}]
(tmp / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
(tmp / "players.json").write_text(json.dumps({"players": [{"github": "boss", "name": "주인", "main": True},
                                                          {"id": "p1", "name": "1호", "agent": "선수"},
                                                          {"id": "kim", "name": "김", "email": "kim@example.com"}],
                                              "league": {"name": "시험", "contests": []}}, ensure_ascii=False), encoding="utf-8")
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
    p.write_text(json.dumps({"symbol": key, "market": market, "currency": ccy, "name": name or key,
                             "bars": [{"d": d, "o": c, "h": c, "l": c, "c": c} for d, c in rows]}, ensure_ascii=False), encoding="utf-8")


def minutes(key, d, rows):
    p = tmp / "data" / "minutes" / key / f"{d}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"step": 60, "src": "시험", "bars": [[ts(r[0]), *r[1:]] for r in rows]}), encoding="utf-8")


def run(now, *args, ok=True, home=None):
    e = {**os.environ, "PAPER_HOME": str(home or tmp), "PAPER_NOW": now + "+09:00", "PAPER_OFFLINE": "1",
         "PYTHONIOENCODING": "utf-8", "GITHUB_ACTIONS": ""}
    r = subprocess.run([sys.executable, str(BROKER), *args], env=e, capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode != 0:
        raise SystemExit(f"명령 실패 {args}: {r.stdout}{r.stderr}")
    return r


def put(folder, name, req):
    d = tmp / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")


def acct(aid):
    return json.loads((tmp / "docs" / "data" / "accounts" / f"{aid}.json").read_text(encoding="utf-8"))


def league():
    return json.loads((tmp / "docs" / "data" / "league.json").read_text(encoding="utf-8"))


def ledger(aid):
    return [json.loads(x) for x in (tmp / "accounts" / aid / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]


def roster():
    return json.loads((tmp / "players.json").read_text(encoding="utf-8"))["players"]


daily("069500", "KR", "KRW", [("2026-11-13", 50000), ("2026-11-16", 50000), ("2026-11-17", 51000)], name="KODEX 200")
daily("005930", "KR", "KRW", [("2026-11-13", 100000), ("2026-11-16", 101000), ("2026-11-17", 103000)], name="삼성전자")
minutes("005930", "2026-11-16", [("2026-11-16T09:00", 100000, 100500, 99500, 100000, 100000, "r"),
                                 ("2026-11-16T15:30", 101000, 101000, 101000, 101000, 1000, "r")])

print("준비: p1 이 사고, 걸어 둔 주문·지켜보기가 있다")
run("2026-11-15T10:00:00", "open")
run("2026-11-15T10:00:00", "daily")
put("inbox/p1", "a1", {"client_id": "a1", "symbol": "005930", "side": "buy", "qty": 10, "ref": "D1"})
put("inbox/p1", "a2", {"client_id": "a2", "symbol": "005930", "side": "buy", "qty": 5, "type": "limit", "price": 90000, "ref": "D2"})
put("inbox/p1", "a3", {"client_id": "a3", "action": "watch", "symbol": "005930", "when": "close_below", "value": 80000, "ref": "D1"})
run("2026-11-15T10:01:00", "ingest")
run("2026-11-16T16:10:00", "daily")
s1 = acct("p1")
check("p1 이 10주를 샀다", any(p["symbol"] == "005930" and p["qty"] == 10 for p in s1["positions"]), s1["positions"])

print("분기 요청")
put("inbox/p1", "f0", {"client_id": "f0", "action": "fork", "ref": "D3"})
put("inbox/p1", "f1", {"client_id": "f1", "action": "fork", "ref": "D3",
                       "arguments": {"그대로": "지금 비중을 지킨다 — 비밀 논거 하나", "줄이기": "절반을 판다 — 비밀 논거 둘"}})
put("inbox/p1", "f2", {"client_id": "f2", "action": "fork", "ref": "D4", "arguments": "또"})
put("inbox", "fm", {"client_id": "fm", "action": "fork", "arguments": "주인 계좌"})
run("2026-11-16T17:00:00", "ingest")
run("2026-11-16T17:00:00", "build")
s1, L = acct("p1"), league()
why = {r["client_id"]: r["why"] for r in s1["refused"]}
f = next(x for x in s1["forks"] if x["client_id"] == "f1")
check("논거 글이 없으면 받지 않는다", "논거" in why.get("f0", ""), why)
check("요청을 받으면 F0001 승인 대기", f["id"] == "F0001" and f["status"] == "requested" and f["ref"] == "D3", f)
check("기다리는 요청이 있으면 또 받지 않는다", "기다리는" in why.get("f2", ""), why)
main = json.loads((tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8"))
check("주인(사람) 계좌는 분기를 요청할 수 없다", any("에이전트 계좌만" in r["why"] for r in main["refused"]), main["refused"])
raw = json.dumps(s1, ensure_ascii=False) + (tmp / "accounts" / "p1" / "ledger.jsonl").read_text(encoding="utf-8")
check("논거 글은 장부·계좌 화면 자료에 실리지 않는다", "비밀 논거" not in raw)
req = L["fork_requests"]
check("관리자 자료(league.json)의 승인 대기 칸에만 논거 글이 보인다", len(req) == 1 and req[0]["account"] == "p1"
      and req[0]["arguments"]["줄이기"].startswith("절반을 판다"), req)
r = run("2026-11-16T17:00:00", "--account", "p1", "check", "--json", json.dumps({"action": "fork", "arguments": "x"}), ok=False)
check("보내기 전 검사도 된다 (기다리는 요청이 있어 안 됨)", r.returncode == 3 and "기다리는" in r.stdout, r.stdout)

print("승인 — 다음 정기 실행에서 갈라진다")
n1 = len(ledger("p1"))
put("admin", "x1", {"action": "approve_fork", "account": "p1", "fork": "F0001"})
put("admin", "x2", {"action": "approve_fork", "account": "p1", "fork": "F0009"})
run("2026-11-16T17:05:00", "admin-inbox")
log = json.loads((tmp / "docs" / "data" / "admin_log.json").read_text(encoding="utf-8"))
check("승인은 장부에 적히고, 없는 요청은 하지 않는다", log[-2]["ok"] and not log[-1]["ok"] and ledger("p1")[-1]["type"] == "fork_approve", log[-2:])
check("승인하면 논거 글을 지운다 (자료 폴더에서)", not list((tmp / "forks").glob("*.json")))
check("승인만으로는 아무것도 갈라지지 않는다", not (tmp / "accounts" / "p2").exists() and len(ledger("p1")) == n1 + 1)
run("2026-11-17T16:10:00", "daily")
p1l, p2l = ledger("p1"), ledger("p2")
k = p2l[-1]["data"]["at_seq"]
check("복제본은 원본의 그때까지 줄을 그대로 이어받는다 (지문 사슬 그대로)", p2l[:k] == p1l[:k] and p2l[-1]["type"] == "fork" and p2l[-1]["data"]["role"] == "child"
      and p2l[-1]["data"]["head"] == p1l[k - 1]["hash"], (k, len(p1l), len(p2l)))
check("원본 장부에는 '여기서 p2 가 갈라져 나감'", p1l[-1]["type"] == "fork" and p1l[-1]["data"]["role"] == "parent" and p1l[-1]["data"]["child"] == "p2")
check("두 장부 모두 지문 이상 없음", run("2026-11-17T16:20:00", "verify").returncode == 0)
s1, s2 = acct("p1"), acct("p2")
pos = lambda s: [(p["symbol"], p["qty"], p["cost_krw"]) for p in s["positions"]]
check("보유·예수금이 똑같이 따라간다", pos(s1) == pos(s2) and s1["summary"]["cash_krw"] == s2["summary"]["cash_krw"], (pos(s1), pos(s2)))
open_ = lambda s: sorted((o["id"], o["status"]) for o in s["orders"] if o["status"] in ("pending", "partial"))
check("대기 주문·지켜보기도 따라간다", open_(s1) == open_(s2) and open_(s2) and [w["id"] for w in s2["watches"] if w["status"] == "watching"] == ["W0001"],
      (open_(s1), open_(s2)))
check("수익률은 원본의 처음부터 이어진다", s2["opened"] == s1["opened"] and s2["equity"][0]["d"] == s1["equity"][0]["d"])
check("계보: 복제본 lineage, 원본 children·forks", s2["lineage"]["parent"] == "p1" and s2["lineage"]["fork"] == "F0001"
      and s1["children"][0]["child"] == "p2" and s1["forks"][0]["status"] == "done" and s1["forks"][0]["child"] == "p2", (s2["lineage"], s1["children"]))
check("복제본에는 원본 시절의 분기 요청이 나오지 않는다", s2["forks"] == [] and s2["children"] == [], s2["forks"])
new = next(p for p in roster() if p.get("id") == "p2")
check("명단: p2 '2호', 에이전트·부모·갈라진 때", new["name"] == "2호" and new["agent"] == "선수" and new["parent"] == "p1" and new["fork"] == "F0001", new)
L = league()
fam = L["families"][0] if L["families"] else {}
check("league.json: 가지(가계)와 갈라진 날 기준 비교 칸", fam.get("root") == "p1" and fam.get("members") == ["p1", "p2"]
      and fam["forks"][0]["child"] == "p2" and set(fam["forks"][0]["since"]) == {"p1", "p2"}
      and next(r for r in L["players"] if r["id"] == "p2")["parent"] == "p1" and L["fork_requests"] == [], fam)
check("흐름에 갈라진 일이 남는다", any(x["type"] == "fork" and "갈라져" in x["text"] for x in s2["feed"])
      and any(x["type"] == "fork" and "p2" in x["text"] for x in s1["feed"]))
run("2026-11-18T16:10:00", "daily")
check("다시 돌아도 또 갈라지지 않는다", not (tmp / "accounts" / "p3").exists() and len(roster()) == 4)

print("형제는 따로 돈다")
put("inbox/p2", "b1", {"client_id": "b1", "action": "cancel", "order": "O0002", "why": "p2 만"})
run("2026-11-18T16:20:00", "ingest")
run("2026-11-18T16:20:00", "build")
check("한쪽의 취소는 다른 쪽에 영향이 없다", [o["status"] for o in acct("p2")["orders"] if o["id"] == "O0002"] == ["canceled"]
      and [o["status"] for o in acct("p1")["orders"] if o["id"] == "O0002"] == ["pending"])

print("상한 (fork_max_accounts)")
cfg2 = {**cfg, "fork_max_accounts": 2}
(tmp / "config.json").write_text(json.dumps(cfg2, ensure_ascii=False), encoding="utf-8")
put("inbox/p2", "g1", {"client_id": "g1", "action": "fork", "arguments": "더"})
run("2026-11-18T16:30:00", "ingest")
run("2026-11-18T16:30:00", "build")
check("가지의 계좌가 상한이면 받지 않는다", any("최대 2개" in r["why"] for r in acct("p2")["refused"]), acct("p2")["refused"])
(tmp / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

print("거절")
put("inbox/p2", "g2", {"client_id": "g2", "action": "fork", "arguments": {"a": "가", "b": "나"}})
run("2026-11-18T16:40:00", "ingest")
put("admin", "y1", {"action": "reject_fork", "account": "p2", "fork": "F0002", "why": "아직 이르다"})
run("2026-11-18T16:41:00", "admin-inbox")
run("2026-11-19T16:10:00", "daily")
f = next(x for x in acct("p2")["forks"] if x["id"] == "F0002")
check("거절하면 rejected + 사유, 글은 지우고 갈라지지 않는다", f["status"] == "rejected" and f["why"] == "아직 이르다"
      and not list((tmp / "forks").glob("*.json")) and not (tmp / "accounts" / "p3").exists(), f)

print("화면 이름 바꾸기 (주인)")
put("admin", "z1", {"action": "add_player", "id": "p2", "name": "신중한 2호"})
run("2026-11-19T16:20:00", "admin-inbox")
check("이름표는 그대로, 화면 이름만 바뀐다", next(p for p in roster() if p.get("id") == "p2")["name"] == "신중한 2호")

print("에이전트 열쇠 (지문만 명단에)")
H = "ab" * 32
put("admin", "k1", {"action": "set_key", "id": "p2", "hash": H, "label": "선수"})
put("admin", "k2", {"action": "set_key", "id": "p2", "hash": "zz"})
put("admin", "k3", {"action": "set_key", "id": "nobody", "hash": H})
run("2026-11-19T16:30:00", "admin-inbox")
run("2026-11-19T16:31:00", "build")
log = json.loads((tmp / "docs" / "data" / "admin_log.json").read_text(encoding="utf-8"))
p2 = next(p for p in roster() if p.get("id") == "p2")
check("열쇠 지문이 명단에 붙고, 이상한 지문·없는 계좌는 하지 않는다", p2["api_keys"][0]["hash"] == H and [x["ok"] for x in log[-3:]] == [True, False, False], log[-3:])
blob = "".join(f.read_text(encoding="utf-8") for f in (tmp / "docs" / "data").rglob("*.json"))
check("열쇠 지문은 화면 자료(state·league·계좌)에 실리지 않는다", H not in blob and "api_keys" not in blob)
put("admin", "k4", {"action": "revoke_key", "id": "p2"})
run("2026-11-19T16:32:00", "admin-inbox")
check("열쇠 끊기", "api_keys" not in next(p for p in roster() if p.get("id") == "p2"))

print("참가 신청 수락·거절 (주인)")
pend = tmp / "applications" / "pending"
pend.mkdir(parents=True, exist_ok=True)
A1, A2, A3 = "ap-20261119170000000-aaaaaaaa", "ap-20261119170000000-bbbbbbbb", "ap-20261119170000000-cccccccc"
(pend / f"{A1}.json").write_text(json.dumps({"id": A1, "real_name": "김철수", "name": "돌쇠", "agent": "돌쇠봇", "want_id": "dolsoe",
                                             "claim_hash": "c" * 64, "status": "pending"}, ensure_ascii=False), encoding="utf-8")
(pend / f"{A2}.json").write_text(json.dumps({"id": A2, "real_name": "이영희", "name": "영희", "want_id": "p1", "claim_hash": "d" * 64,
                                             "status": "pending"}, ensure_ascii=False), encoding="utf-8")
(pend / f"{A3}.json").write_text(json.dumps({"id": A3, "real_name": "박민수", "name": "민수", "claim_hash": "e" * 64, "status": "pending"},
                                            ensure_ascii=False), encoding="utf-8")
run("2026-11-19T17:10:00", "build")
L = league()
check("기다리는 신청이 관리자 자료에 실명과 함께 (찾아갈 번호 지문은 빼고)", {a["real_name"] for a in L["applications"]} == {"김철수", "이영희", "박민수"}
      and all("claim_hash" not in a for a in L["applications"]), L["applications"])
put("admin", "q1", {"action": "approve_application", "id": A1})
put("admin", "q2", {"action": "approve_application", "id": A2})
put("admin", "q3", {"action": "reject_application", "id": A3, "why": "다음 기회에"})
put("admin", "q4", {"action": "approve_application", "id": A1})
run("2026-11-19T17:11:00", "admin-inbox")
log = json.loads((tmp / "docs" / "data" / "admin_log.json").read_text(encoding="utf-8"))
r1 = next(p for p in roster() if p.get("application") == A1)
r2 = next(p for p in roster() if p.get("application") == A2)
done = {a: json.loads((tmp / "applications" / "done" / f"{a}.json").read_text(encoding="utf-8")) for a in (A1, A2, A3)}
check("수락: 바라는 이름표로 계좌가 열리고 실명이 명단에", r1["id"] == "dolsoe" and r1["real_name"] == "김철수" and r1["agent"] == "돌쇠봇"
      and (tmp / "accounts" / "dolsoe" / "ledger.jsonl").exists() and done[A1]["status"] == "approved" and done[A1]["account"] == "dolsoe", r1)
check("바라는 이름표가 이미 있으면 f번호로", r2["id"] == "f1" and done[A2]["account"] == "f1", r2)
check("거절: rejected + 사유, 계좌 없음", done[A3]["status"] == "rejected" and done[A3]["why"] == "다음 기회에" and not any(p.get("application") == A3 for p in roster()))
check("같은 신청을 두 번 정하지 않는다, 처리한 신청은 기다리는 칸에서 빠진다", log[-1]["ok"] is False and not list(pend.glob("*.json")), log[-1])
run("2026-11-19T17:12:00", "build")
blob = (tmp / "docs" / "data" / "accounts" / "dolsoe.json").read_text(encoding="utf-8") + (tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8")
check("실명은 계좌 화면 자료에 실리지 않는다 (관리자 자료에만)", "김철수" not in blob and next(r for r in league()["players"] if r["id"] == "dolsoe")["real_name"] == "김철수")

put("admin", "e0", {"action": "add_player", "id": "dolsoe", "email": "kim@example.com"})
put("admin", "e1", {"action": "clear_login", "id": "dolsoe"})
put("admin", "e2", {"action": "clear_login", "id": "dolsoe"})
run("2026-11-19T17:13:00", "admin-inbox")
log = json.loads((tmp / "docs" / "data" / "admin_log.json").read_text(encoding="utf-8"))
d = next(p for p in roster() if p.get("id") == "dolsoe")
check("로그인 이메일 지우기: 이메일만 빠지고 계좌는 그대로, 두 번째는 할 것 없음", "email" not in d and d["real_name"] == "김철수"
      and log[-2]["ok"] and not log[-1]["ok"] and (tmp / "accounts" / "dolsoe" / "ledger.jsonl").exists(), (d, log[-2:]))

print("검사만 (dry_run 요청 — 에이전트 API)")
n = len(ledger("p2"))
put("inbox/p2", "d1", {"client_id": "d1", "symbol": "005930", "side": "buy", "qty": 1, "dry_run": True})
put("inbox/p2", "d2", {"client_id": "d2", "symbol": "005930", "side": "buy", "qty": 100000, "dry_run": True})
run("2026-11-19T16:40:00", "ingest")
chk = {x["client_id"]: x for x in json.loads((tmp / "docs" / "data" / "checks" / "p2.json").read_text(encoding="utf-8"))}
check("검사 결과가 checks/{이름표}.json 에 남고 장부는 그대로", chk["d1"]["ok"] and not chk["d2"]["ok"] and "모자랍니다" in chk["d2"]["why"]
      and len(ledger("p2")) == n and not list((tmp / "inbox" / "p2").glob("*.json")), chk)
put("inbox/p2", "c8", {"client_id": "c8", "symbol": "005930", "side": "buy", "qty": 1, "type": "limit", "price": 80000})
put("inbox/p2", "c9", {"client_id": "c9", "action": "cancel", "order": "O0003", "why": "시험"})
run("2026-11-19T16:41:00", "ingest")
run("2026-11-19T16:41:00", "build")
o3 = next(o for o in acct("p2")["orders"] if o["id"] == "O0003")
check("취소 요청 번호가 그 주문의 결과에 남는다 (요청 결과 찾기용)", o3["status"] == "canceled" and o3["result"]["client_id"] == "c9", o3)

print("자기 계좌만 받아 간 폴더 (형제 가리기)")
mine = Path(tempfile.mkdtemp(prefix="paper_mine_"))
for rel in ("accounts/p2", "data", "docs/data/accounts/p2.json"):
    src, dst = tmp / rel, mine / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    (shutil.copytree if src.is_dir() else shutil.copy)(src, dst)
(mine / ".ledger-lock").write_text("", encoding="utf-8")
r = run("2026-11-19T17:00:00", "--account", "p2", "check", "--json", json.dumps({"symbol": "005930", "side": "buy", "qty": 1}), ok=False, home=mine)
check("명단 없이도 자기 계좌로 검사(check)가 된다", r.returncode == 0 and json.loads(r.stdout.strip().splitlines()[-1])["ok"], r.stdout + r.stderr)
r2 = run("2026-11-19T17:00:00", "--account", "p2", "quote", "--symbol", "005930", ok=False, home=mine)
r3 = run("2026-11-19T17:00:00", "--account", "p2", "status", ok=False, home=mine)
check("값 묻기(quote)·상태 보기(status)도 된다", r2.returncode == 0 and r3.returncode == 0 and "10주" in r3.stdout, r2.stdout + r3.stdout + r3.stderr)
r4 = run("2026-11-19T17:00:00", "--account", "p1", "status", ok=False, home=mine)
r5 = run("2026-11-19T17:00:00", "--account", "p2", "order", "--symbol", "005930", "--side", "buy", "--qty", "1", ok=False, home=mine)
check("형제 계좌는 없고, 쓰는 명령은 잠겨 있다", r4.returncode != 0 and r5.returncode != 0 and "클라우드" in (r5.stdout + r5.stderr), r4.stdout + r5.stdout + r5.stderr)

if os.environ.get("KEEP_TMP"):
    print("남겨 둠:", tmp)
else:
    shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(mine, ignore_errors=True)
print(f"\n{'전부 통과' if not fails else '실패 ' + str(len(fails)) + '건'}")
sys.exit(1 if fails else 0)
