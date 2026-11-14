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
cfg.update({"league": {"name": "시험 대회"},
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


def issue(now, author, number, body):
    reply = tmp / "reply.md"
    reply.unlink(missing_ok=True)
    run(now, "issue", env={"PAPER_ISSUE_AUTHOR": author, "PAPER_ISSUE_NUMBER": str(number),
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
check("모든 장부의 지문이 맞는다", run(WED, "verify").returncode == 0)
led = tmp / "accounts" / "alice" / "ledger.jsonl"
led.write_text(led.read_text(encoding="utf-8").replace('"qty": 100', '"qty": 900'), encoding="utf-8")
check("한 사람 장부라도 손대면 검증이 실패한다", run(WED, "verify", ok=False).returncode != 0)
check("--account 로 한 계좌만 본다", "원화 예수금 50,000,000원" in run(WED, "--account", "bob99", "status").stdout)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'전부 통과' if not fails else '실패 ' + str(len(fails)) + '건'}")
sys.exit(1 if fails else 0)
