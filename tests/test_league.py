"""여러 참가자 시험 — 계좌 분리, 주문 이슈 접수(본인 확인), 순위표. 임시 폴더와 가짜 시세로만 돈다.

실행: python tests/test_league.py
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
tmp = Path(tempfile.mkdtemp(prefix="paper_league_"))
cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
cfg.update({"league": {"name": "시험 대회", "contests": [{"name": "이틀 대회", "start": "2026-11-03", "end": "2026-11-04"},
                                                    {"name": "다음 달 대회", "start": "2026-12-01", "end": "2026-12-31"}]},
            "players": [{"github": "Owner-Kim", "name": "주인", "main": True},
                        {"github": "alice", "name": "앨리스", "agent": "시험 에이전트"},
                        {"github": "Bob99", "name": "밥"},
                        {"github": "../evil", "name": "나쁜 이름"}]})        # 파일 이름이 될 수 없는 계정은 건너뛴다
(tmp / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
DAYS = ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"]


def daily(key, market, prices):
    p = tmp / "data" / "prices" / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"symbol": key, "market": market, "currency": "KRW", "name": key + " 시험",
                             "bars": [{"d": d, "o": v, "h": v, "l": v, "c": v} for d, v in zip(DAYS, prices)]},
                            ensure_ascii=False), encoding="utf-8")


daily("000010", "KR", [10000, 10000, 11000, 12000])          # 오른다
daily("000020", "KR", [20000, 20000, 19000, 18000])          # 내린다
daily("069500", "KR", [80000] * 4)
daily("QQQ", "US", [600] * 4)
daily("USDKRW", "FX", [1300] * 4)


def run(now, *args, ok=True, env=None):
    e = {**os.environ, "PAPER_HOME": str(tmp), "PAPER_NOW": now, "PYTHONIOENCODING": "utf-8", **(env or {})}
    r = subprocess.run([sys.executable, str(BROKER), *args], env=e, capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode != 0:
        raise SystemExit(f"명령 실패 {args}: {r.stdout}{r.stderr}")
    return r


def issue(now, author, number, body, title="[주문] 시험"):
    reply = tmp / "reply.md"
    reply.unlink(missing_ok=True)
    run(now, "issue", env={"PAPER_ISSUE_AUTHOR": author, "PAPER_ISSUE_NUMBER": str(number), "PAPER_ISSUE_TITLE": title,
                           "PAPER_ISSUE_BODY": body if isinstance(body, str) else json.dumps(body, ensure_ascii=False),
                           "PAPER_REPLY": str(reply)})
    return reply.read_text(encoding="utf-8")


def ledger(acct=None):
    f = tmp / "ledger" / "ledger.jsonl" if acct is None else tmp / "accounts" / acct / "ledger.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def state(acct):
    return json.loads((tmp / "docs" / "data" / "accounts" / f"{acct}.json").read_text(encoding="utf-8"))


fails = []


def check(label, cond, detail=""):
    print(("  통과 " if cond else "  실패 ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)


MON = "2026-11-02T08:00:00+09:00"
run(MON, "open")                                                                # 주인 계좌 (예전 자리)
run(MON, "order", "--symbol", "000020", "--side", "buy", "--qty", "100", "--type", "moc")       # 주인: 내리는 종목

# 참가자는 주문 이슈로 — 이슈를 쓴 계정이 곧 계좌
r = issue(MON, "alice", 11, {"symbol": "000010", "side": "buy", "qty": 100, "type": "moc", "ref": "A1"})
check("주문 이슈가 접수되고 답글에 주문 번호가 나온다", "주문 번호 O0001" in r and "앨리스" in r, r)
check("참가자 계좌는 첫 주문 때 같은 시작 금액으로 열린다", ledger("alice")[0]["type"] == "open"
      and ledger("alice")[0]["data"]["initial_cash"] == cfg["initial_cash"] and ledger("alice")[0]["data"]["player"] == "alice")
check("주문은 그 사람 장부에만 적힌다", [e["type"] for e in ledger("alice")] == ["open", "order"]
      and [e["type"] for e in ledger()] == ["open", "order"] and [e["type"] for e in ledger("bob99")] == ["open"])
r = issue(MON, "ALICE", 12, "주문합니다\n```json\n" + json.dumps([
    {"symbol": "000010", "side": "buy", "krw": 1000000, "type": "moc"},
    {"symbol": "ZZZ", "side": "sell", "qty": 1}]) + "\n```\n잘 부탁합니다")
check("한 이슈에 여러 주문, 계정 대소문자는 가리지 않는다", "주문 번호 O0002" in r and "받지 않았습니다" in r and "보유하고 있지 않습니다" in r, r)
r = issue(MON, "bob99", 13, {"account": "alice", "symbol": "000010", "side": "sell", "qty": "all"})
check("남의 계좌 이름을 적어도 자기 계좌로만 처리된다 (앨리스 것을 팔 수 없다)", "받지 않았습니다" in r
      and len(ledger("alice")) == 4 and ledger("bob99")[-1]["type"] == "refuse", r)
n = {a: len(ledger(a)) for a in (None, "alice", "bob99")}
r = issue(MON, "mallory", 14, {"symbol": "000010", "side": "buy", "qty": 1})
check("명단에 없는 계정의 주문은 받지 않고 어느 장부에도 적지 않는다", "명단에 없어" in r
      and n == {a: len(ledger(a)) for a in (None, "alice", "bob99")} and not (tmp / "accounts" / "mallory").exists(), r)
r = issue(MON, "bob99", 15, "아무 말이나 적은 이슈")
check("읽을 수 없는 주문 이슈는 사유와 함께 장부에 남는다", "읽을 수 없습니다" in r and ledger("bob99")[-1]["type"] == "refuse", r)
r = issue(MON, "bob99", 16, {"symbol": "000010", "side": "buy", "qty": "많이", "valid_days": "x"})
check("엉뚱한 값이 와도 멈추지 않고 받지 않는다", "받지 않았습니다" in r, r)
r = issue(MON, "bob99", 17, [{"symbol": "000010", "side": "buy", "qty": 1}] * 11)
check("한 이슈에 주문이 너무 많으면 받지 않는다", "읽을 수 없습니다" in r, r)
n = len(ledger("alice"))
issue(MON, "alice", 11, {"symbol": "000010", "side": "buy", "qty": 100, "type": "moc"})
check("같은 이슈를 두 번 처리해도 주문은 한 번", len(ledger("alice")) == n)
check("파일 이름이 될 수 없는 계정은 계좌가 생기지 않는다", sorted(p.name for p in (tmp / "accounts").iterdir()) == ["alice", "bob99"])
n_alice = len(ledger("alice"))

# 로그인이 있는 화면에서 들어오는 주문: inbox/{계정}/ 폴더가 곧 계좌
box = tmp / "inbox"
(box / "alice").mkdir(parents=True)
(box / "bob99").mkdir()
(box / "mallory").mkdir()
(box / "alice" / "w1.json").write_text(json.dumps({"client_id": "web-1", "account": "bob99", "symbol": "000010", "side": "buy", "qty": 1,
                                                    "type": "limit", "price": 8400}), encoding="utf-8")
(box / "bob99" / "w2.json").write_text(json.dumps({"symbol": "ZZZ", "side": "sell", "qty": 1}), encoding="utf-8")
(box / "mallory" / "w3.json").write_text(json.dumps({"symbol": "000010", "side": "buy", "qty": 1}), encoding="utf-8")
n_own = len(ledger())
out = run(MON, "ingest").stdout
check("계좌별 창구: 폴더 이름의 계좌로 접수된다 (요청 안의 계좌 이름은 보지 않는다)", ledger("alice")[-1]["type"] == "order"
      and ledger("alice")[-1]["data"]["client_id"] == "web-1" and ledger("bob99")[-1]["type"] == "refuse" and len(ledger()) == n_own, out)
check("처리한 요청 파일은 치우고, 명단에 없는 폴더는 건드리지 않는다", not list((box / "alice").glob("*.json")) and not list((box / "bob99").glob("*.json"))
      and (box / "mallory" / "w3.json").exists() and "명단에 없는" in out, out)

# 관리 이슈: 주인 계정만 참가자를 넣고 빼고 대회를 정한다
r = issue(MON, "alice", 30, {"action": "add_player", "github": "carol"}, title="[관리] 넣기")
check("주인이 아닌 계정의 관리 명령은 받지 않는다", "주인만" in r and not (tmp / "accounts" / "carol").exists()
      and len(json.loads((tmp / "config.json").read_text(encoding="utf-8"))["players"]) == 4, r)
r = issue(MON, "owner-kim", 31, [{"action": "add_player", "github": "Carol", "name": "캐럴", "agent": "새 에이전트"},
                                  {"action": "add_contest", "name": "새 대회", "start": "2027-01-01", "end": "2027-01-31"},
                                  {"action": "add_player", "github": "../x"},
                                  {"action": "remove_player", "github": "owner-kim"}], title="[관리] 넣기")
c2 = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
check("주인의 관리 명령: 참가자를 넣으면 계좌가 바로 열리고, 대회 기간이 설정에 적힌다", "명단에 넣었습니다" in r and ledger("carol")[0]["type"] == "open"
      and {"github": "Carol", "name": "캐럴", "agent": "새 에이전트"} in c2["players"]
      and {"name": "새 대회", "start": "2027-01-01", "end": "2027-01-31"} in c2["league"]["contests"], r)
check("이상한 계정 이름과 주인 계좌 빼기는 하지 않는다", r.count("하지 않았습니다") == 2 and any(p.get("main") for p in c2["players"]), r)
r = issue(MON, "carol", 32, {"symbol": "000010", "side": "buy", "qty": 1, "type": "moc"})
check("새로 들어온 참가자가 바로 주문할 수 있다", "주문 번호 O0001" in r, r)
r = issue(MON, "Owner-Kim", 33, [{"action": "remove_player", "github": "carol"}, {"action": "remove_contest", "name": "새 대회"}], title="[관리] 빼기")
c3 = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
check("참가자를 빼면 명단에서 빠지고 장부는 남는다", "명단에서 뺐습니다" in r and not any(str(p.get("github")).lower() == "carol" for p in c3["players"])
      and len(ledger("carol")) == 2 and not any(c["name"] == "새 대회" for c in c3["league"]["contests"]), r)
r = issue(MON, "carol", 34, {"symbol": "000010", "side": "buy", "qty": 1})
check("빠진 사람의 주문은 받지 않는다", "명단에 없어" in r and len(ledger("carol")) == 2, r)

# 체결과 순위
WED = "2026-11-05T09:00:00+09:00"
run(WED, "settle")
run(WED, "build")
al, bob, own = state("alice"), state("bob99"), state("owner-kim")
main_state = json.loads((tmp / "docs" / "data" / "state.json").read_text(encoding="utf-8"))
check("계좌마다 따로 체결된다", al["summary"]["n_filled"] == 2 and own["summary"]["n_filled"] == 1 and bob["summary"]["n_filled"] == 0, str(al["summary"]))
check("주인 계좌는 예전 자리(state.json)에도 그대로 나온다", main_state["summary"] == own["summary"] and main_state["account"] == cfg["account_name"])
check("화면 자료에 누구 계좌인지 실린다", al["account"] == "앨리스" and al["player"]["github"] == "alice" and al["player"]["agent"] == "시험 에이전트")
lg = json.loads((tmp / "docs" / "data" / "league.json").read_text(encoding="utf-8"))
rows = lg["players"]
check("순위표: 수익률 순 (오른 종목을 산 앨리스 1위, 아무것도 안 한 밥 2위, 내린 종목을 산 주인 3위)",
      [(x["rank"], x["id"]) for x in rows] == [(1, "alice"), (2, "bob99"), (3, "owner-kim")] and lg["name"] == "시험 대회", str([(x["rank"], x["id"], x["pnl_pct"]) for x in rows]))
check("순위표 숫자는 계좌 화면 자료와 같다", rows[0]["total"] == al["summary"]["total"] and rows[0]["pnl_pct"] == al["summary"]["pnl_pct"]
      and rows[0]["name"] == "앨리스" and rows[0]["n_positions"] == 1)
# 수익률 재기: 기간 수익률 = 끝 날 총자산 ÷ 시작 전날 총자산 − 1
eq = {e["d"]: e["total"] for e in al["equity"]}
pf = {p["key"]: p for p in al["performance"]["periods"]}
check("처음부터의 수익률은 시작 금액 기준이고 요약의 수익률과 같다", pf["all"]["pct"] == al["summary"]["pnl_pct"] and pf["all"]["from_open"]
      and pf["all"]["from"] == "2026-11-02" and pf["all"]["to"] == "2026-11-04", str(pf["all"]))
check("계좌가 그 기간보다 젊으면 '최근 1주' 같은 칸은 비워 둔다", "w1" not in pf and "m1" not in pf and "ytd" in pf, str(list(pf)))
check("최대 낙폭: 오르기만 한 계좌는 0, 내리기만 한 계좌는 시작 금액부터 잰다", al["performance"]["max_drawdown"]["pct"] == 0
      and own["performance"]["max_drawdown"]["pct"] == own["summary"]["pnl_pct"], str(own["performance"]["max_drawdown"]))
cs = {c["name"]: c for c in lg["contests"]}
c1 = {x["id"]: x for x in cs["이틀 대회"]["players"]}
want = round((eq["2026-11-04"] / eq["2026-11-02"] - 1) * 100, 2)
check("대회 = 이름 붙인 기간: 시작 전날(11-02) 총자산을 기준으로 그 기간만 잰다", c1["alice"]["pct"] == want and c1["alice"]["rank"] == 1
      and not c1["alice"]["late"] and c1["alice"]["to"] == "2026-11-04" and cs["이틀 대회"]["status"] == "끝남", f"{c1['alice']} vs {want}")
check("대회 순위는 전체 순위와 따로 매긴다", [x["id"] for x in cs["이틀 대회"]["players"]] == ["alice", "bob99", "owner-kim"])
check("아직 시작하지 않은 대회는 '예정'이고 순위가 비어 있다", cs["다음 달 대회"]["status"] == "예정" and cs["다음 달 대회"]["players"] == [])
check("순위표에 기간별 수익률이 실린다", rows[0]["returns"]["all"]["pct"] == al["summary"]["pnl_pct"] and rows[0]["max_drawdown_pct"] == 0)

# 수익률 계산을 숫자로 직접 확인 (가짜 자산 곡선)
os.environ["PAPER_HOME"] = str(tmp)
sys.path.insert(0, str(ROOT / "broker"))
import broker as bk  # noqa: E402
curve = [{"d": f"2026-0{m}-{d:02d}", "total": t, "bench": b} for m, d, t, b in [
    (1, 5, 100, 100), (1, 6, 110, 100), (1, 7, 99, 102), (2, 2, 120, 105), (2, 5, 132, 105), (2, 6, 132, 110), (2, 9, 138.6, 110)]]
r = bk.span_return(curve, 100, "2026-02-05", "2026-02-06")
check("기간 수익률: 2-05~2-06 은 2-02 의 120 을 기준으로 +10%, 비교 기준은 105→110", r["pct"] == 10.0 and r["bench_pct"] == 4.76
      and r["excess_pct"] == 5.24 and not r["late"], str(r))
r = bk.span_return(curve, 100, "2025-12-01", "2026-01-06")
check("기간이 계좌보다 먼저 시작하면 시작 금액을 기준으로 재고 늦게 들어온 것으로 표시", r["pct"] == 10.0 and r["late"] and r["from"] == "2026-01-05", str(r))
check("자료가 없는 기간은 재지 않는다", bk.span_return(curve, 100, "2026-03-01") is None)
pfm = bk.performance(curve, 100)
k = {p["key"]: p for p in pfm["periods"]}
check("최근 1주(2-03~2-09)는 2-02 의 120 기준 +15.5%, 처음부터는 +38.6%", k["w1"]["pct"] == 15.5 and k["all"]["pct"] == 38.6 and k["m1"]["pct"] == 40.0, str(k))
check("최대 낙폭: 110 → 99 = -10%", pfm["max_drawdown"] == {"pct": -10.0, "from": "2026-01-06", "to": "2026-01-07"}, str(pfm["max_drawdown"]))

check("모든 장부의 지문이 맞는다", run(WED, "verify").returncode == 0)
led = tmp / "accounts" / "alice" / "ledger.jsonl"
led.write_text(led.read_text(encoding="utf-8").replace('"qty": 100', '"qty": 900'), encoding="utf-8")
check("한 사람 장부라도 손대면 검증이 실패한다", run(WED, "verify", ok=False).returncode != 0)
check("--account 로 한 계좌만 본다", "원화 예수금 50,000,000원" in run(WED, "--account", "bob99", "status").stdout)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'전부 통과' if not fails else '실패 ' + str(len(fails)) + '건'}")
sys.exit(1 if fails else 0)
