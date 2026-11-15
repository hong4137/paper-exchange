"""모의 증권 거래소 — 계좌·주문·체결·평가만 한다.

거래소는 "왜 샀는지"를 모른다. 결정 기록·보고서·교훈은 운용 일지(통합 개발/모의투자-일지)의 일이다.
주문에는 운용자가 붙인 꼬리표(--ref)만 실려 오고, 거래소는 그 내용을 읽지 않는다.

돈은 원화·달러 두 주머니다. 한국 주식은 원화로, 미국 주식은 달러로 사고판다 (판 돈도 달러로 남는다).
  달러가 모자란 미국 주식 매수는 모자란 만큼만 자동으로 환전한다 (config.json "usd_shortfall": "auto", 아니면 거부).
  비용(수수료·세금·환전)은 config.json "fees", 배당·액면분할은 시세 캐시의 events 를 보고 settle 이 장부에 적는다.
장부 줄 종류: open · order · cancel · fill · reject · expire · refuse · fx(환전) · dividend(배당) · split(분할·병합) · watch·unwatch(값 조건 지켜보기).
  옛 fill 줄(ccy·delta 가 없는 것)은 원화 한 주머니 시절 것으로 읽는다.

참가자가 여럿이다 (config.json "players" — 주인이 넣은 GitHub 계정 명단). 계좌는 참가자마다 하나, 장부도 계좌마다 하나다.
  주인 계좌("main": true)는 예전 자리 그대로: ledger/ledger.jsonl, docs/data/state.json, 주문 창구 inbox/.
  다른 참가자는 accounts/{계정}/ledger.jsonl, docs/data/accounts/{계정}.json. 주문은 본인 GitHub 계정으로 연 "주문 이슈"로만 받는다
  (python broker/broker.py issue — 자동 실행 issue-window 가 부른다. 이슈를 쓴 계정이 곧 계좌다. 요청 안의 계좌 이름은 보지 않는다).
  로그인이 있는 화면에서 들어오는 주문은 inbox/{계정}/ 에 요청 파일로 떨어진다 — 그 폴더 이름이 곧 계좌다 (폴더에 쓰는 쪽이 본인 확인을 책임진다).
  주인은 "[관리]" 이슈로 참가자를 넣고 빼고 대회 기간을 정한다 (주인 계정이 연 이슈만 받는다. config.json 을 고친다).
  시세(data/)는 모두가 함께 쓴다. 전체 계좌 수익률은 docs/data/league.json (관리자 화면 docs/admin.html).
  한 계좌만 다루려면 명령 앞에 --account 계정 (없으면 주인 계좌). update·settle·build·daily·verify 는 모든 계좌를 돈다.

장부는 계좌마다 한 파일이다 (주인 계좌는 {HOME}/ledger/ledger.jsonl). 줄 추가만 하고, 줄마다 앞줄의 지문(hash)을 품는다.
상태(현금·보유·주문 상태)는 장부를 처음부터 다시 읽어 만든다.

쓰는 법 (통합 개발/모의투자 에서):
  python broker/broker.py open                      계좌 개설 (장부가 비었을 때 한 번)
  python broker/broker.py order --symbol MU --side buy --krw 5000000 [--ref D001]        시장가(기본)
  python broker/broker.py order --symbol MU --side buy --qty 10 --type moc               그날 종가에
  python broker/broker.py order --symbol MU --side buy --qty 3 --type limit --price 775 --session all   시간외 포함 지정가
  python broker/broker.py order --symbol MU --side sell --qty all --type stop --price 700
  python broker/broker.py order --symbol USD --side buy --krw 3000000      환전: 원화 300만 원을 달러로 (--usd 2000 처럼 달러 금액도)
  python broker/broker.py order --symbol USD --side sell --usd all         환전: 달러 예수금 전부를 원화로
  python broker/broker.py cancel --order O0001 --why ..
  python broker/broker.py daily                     시세 갱신 → 체결 → 화면 자료 만들기
  python broker/broker.py check --json '{"symbol": "005930", "side": "buy", "qty": 1}'   보내지 않고 검사만 (끝 값 0 받음 · 3 안 받음)
  python broker/broker.py quote --symbol 005930 [--krw 1000000]    거래소가 가진 값·호가 단위·상하한가·몇 주 (읽기만)
  창구 요청 action: order(기본)·cancel·watch(값 조건 지켜보기)·unwatch. 지켜보기는 주문을 내지 않고 state.json watch_hits 에 알리기만 한다.
  python broker/broker.py status | verify
  python broker/broker.py ingest                    주문 창구(inbox/)에 들어온 요청을 접수한다

장부는 거래소 한 곳만 쓴다 (config.json "ledger_writer": "cloud" 일 때 = GitHub 자동 실행).
  운용자는 주문 요청 파일을 inbox/ 에 올리기만 하고, 거래소가 받아서 자기 시각으로 접수한다.
  그래서 이 PC 에서 open·order·cancel·settle·daily·ingest·build 를 직접 돌리면 거절된다 (읽기 전용인 status·verify 는 된다).
시험할 때는 환경변수 PAPER_HOME(임시 폴더), PAPER_NOW(가짜 현재 시각)를 쓴다 — 그때는 잠금이 풀린다.
  단 PAPER_HOME 이 실제 자료 저장소(표지 파일 .ledger-lock 이 있는 폴더)면 풀리지 않는다 — GitHub 자동 실행만 쓴다.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prices as px  # noqa: E402
import matching as mt  # noqa: E402
import markets as mk  # noqa: E402

KST = px.KST
CODE_ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("PAPER_HOME") or CODE_ROOT)
LEDGER = HOME / "ledger" / "ledger.jsonl"
STATE_OUT = HOME / "docs" / "data" / "state.json"
LEAGUE_OUT = HOME / "docs" / "data" / "league.json"
ACCT = {"id": "main", "github": None, "name": None, "agent": None, "main": True}     # 지금 다루는 계좌

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def now():
    v = os.environ.get("PAPER_NOW")
    return datetime.fromisoformat(v).astimezone(KST) if v else datetime.now(KST)


PRIVATE_KEYS = ("players", "league")       # 비공개 자료 쪽(players.json)에 두는 것 — 명단(이메일)·대회


def config():
    """거래소 설정. 규칙·요율·비교 기준은 config.json(공개 엔진 저장소에 있다 — 자료 폴더에 없으면 코드 옆 것),
    명단·대회는 자료 폴더의 players.json(비공개 자료 저장소)이 있으면 그것으로 덮는다."""
    base = HOME / "config.json" if (HOME / "config.json").exists() else CODE_ROOT / "config.json"
    cfg = json.loads(base.read_text(encoding="utf-8"))
    priv = HOME / "players.json"
    if priv.exists():
        cfg.update({k: v for k, v in json.loads(priv.read_text(encoding="utf-8")).items() if k in PRIVATE_KEYS})
    return cfg


# ---------- 계좌 (참가자) ----------
def accounts(cfg=None):
    """참가자 계좌 목록. 명단(players)이 없으면 주인 계좌 하나.
    계좌 이름표(id)는 명단의 id, 없으면 GitHub 계정 이름(소문자). 파일 이름이 되므로 영문·숫자·줄표만 받는다.
    GitHub 계정이 없는 참가자(이메일로 로그인하는 사람)는 id 만 있어도 된다 — 주문 이슈는 못 쓰고 로그인한 화면으로 주문한다."""
    cfg = cfg or config()
    out = []
    for p in cfg.get("players") or []:
        gh = str(p.get("github") or "").strip() or None
        aid = str(p.get("id") or gh or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,38}", aid) or any(x["id"] == aid for x in out):
            continue
        out.append({"id": aid, "github": gh, "name": str(p.get("name") or gh or aid), "agent": p.get("agent"),
                    "main": bool(p.get("main")) and not any(x["main"] for x in out)})
    if not any(x["main"] for x in out):                 # 예전 장부(주인 계좌)는 언제나 남는다
        out.insert(0, {"id": "main", "github": None, "name": cfg["account_name"], "agent": None, "main": True})
    return out


def use(acct):
    """이제부터 이 계좌의 장부·화면 자료를 다룬다."""
    global LEDGER, STATE_OUT, ACCT
    ACCT = acct
    if acct["main"]:
        LEDGER, STATE_OUT = HOME / "ledger" / "ledger.jsonl", HOME / "docs" / "data" / "state.json"
    else:
        LEDGER = HOME / "accounts" / acct["id"] / "ledger.jsonl"
        STATE_OUT = HOME / "docs" / "data" / "accounts" / f"{acct['id']}.json"


def account_label(cfg):
    return cfg["account_name"] if ACCT["main"] else ACCT["name"]


def pick(account_id):
    """--account 로 고른 계좌 (없으면 주인 계좌)."""
    accts = accounts()
    if not account_id:
        return next(x for x in accts if x["main"])
    a = next((x for x in accts if x["id"] == str(account_id).lower()), None)
    if not a:
        sys.exit(f"명단에 없는 계좌입니다: {account_id}")
    return a


def open_missing():
    """명단에 있는데 아직 장부가 없는 참가자의 계좌를 연다 (모두 같은 시작 금액·규칙)."""
    cfg, here = config(), ACCT
    for acct in accounts(cfg):
        use(acct)
        if not read_ledger():
            append("open", {"account": account_label(cfg), "player": acct["github"], "initial_cash": cfg["initial_cash"],
                            "opened": now().date().isoformat(), "fees": fee_cfg(cfg), "rules": cfg["rules"]})
            print(f"계좌 개설: {account_label(cfg)} · {cfg['initial_cash']:,}원")
    use(here)


# ---------- 수익률 재기 ----------
# 넣고 빼는 돈이 없으므로 기간 수익률 = 끝 날의 총자산 ÷ 시작 전날의 총자산 − 1. 자산 곡선(하루 한 점)에서 바로 나온다.
PERIODS = [("w1", "최근 1주", 7), ("m1", "최근 1개월", 30), ("m3", "최근 3개월", 91), ("m6", "최근 6개월", 182), ("y1", "최근 1년", 365)]


def _point_before(equity, date, inclusive=True):
    """date 이하(또는 미만)의 마지막 자산 곡선 점."""
    best = None
    for e in equity:
        if e["d"] < date or (inclusive and e["d"] == date):
            best = e
        else:
            break
    return best


def span_return(equity, initial, start, end=None):
    """start 날부터 end 날까지의 수익률. 기준은 start 전날의 총자산 — 계좌를 start 뒤에 열었으면 시작 금액(늦게 들어온 것으로 표시).
    반환 {from, to, pct, bench_pct, excess_pct, from_open(시작 금액 기준인가), late(start 뒤에 연 계좌인가)} 또는 None(그 기간에 자료가 없다)."""
    if not equity:
        return None
    last = _point_before(equity, end) if end else equity[-1]
    if last is None or last["d"] < start:
        return None
    base = _point_before(equity, start, inclusive=False)
    from_open = base is None
    b_total, b_bench = (initial, initial) if from_open else (base["total"], base["bench"])
    pct = round((last["total"] / b_total - 1) * 100, 2) if b_total else None
    bench = round((last["bench"] / b_bench - 1) * 100, 2) if last.get("bench") and b_bench else None
    return {"from": equity[0]["d"] if from_open else start, "to": last["d"], "pct": pct, "bench_pct": bench,
            "excess_pct": None if pct is None or bench is None else round(pct - bench, 2),
            "from_open": from_open, "late": equity[0]["d"] > start}


def performance(equity, initial):
    """계좌 하나의 성적: 기간별 수익률(비교 기준과 나란히), 최대 낙폭, 하루 수익률의 흔들림."""
    if not equity:
        return None
    last_d = datetime.strptime(equity[-1]["d"], "%Y-%m-%d")
    out = []
    for key, label, days in PERIODS:
        start = (last_d - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        r = span_return(equity, initial, start)
        if r and not r["from_open"]:                    # 계좌가 그 기간보다 젊으면 비워 둔다
            out.append({"key": key, "label": label, **r})
    r = span_return(equity, initial, f"{last_d.year}-01-01")
    if r:
        out.append({"key": "ytd", "label": "올해", **r})
    r = span_return(equity, initial, equity[0]["d"])
    out.append({"key": "all", "label": "처음부터", **r})
    # 최대 낙폭: 지나온 가장 높은 총자산에서 가장 많이 내려간 폭
    peak, peak_d, mdd = initial, equity[0]["d"], {"pct": 0.0, "from": None, "to": None}
    rets, prev = [], initial
    for e in equity:
        if e["total"] > peak:
            peak, peak_d = e["total"], e["d"]
        dd = (e["total"] / peak - 1) * 100 if peak else 0
        if dd < mdd["pct"]:
            mdd = {"pct": round(dd, 2), "from": peak_d, "to": e["d"]}
        if prev:
            rets.append(e["total"] / prev - 1)
        prev = e["total"]
    rets = rets[1:]                                     # 첫 점은 시작 금액과의 차이라 하루 수익률이 아니다
    vol = None
    if len(rets) >= 5:
        m = sum(rets) / len(rets)
        vol = round(math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) * 100, 2)
    return {"periods": out, "max_drawdown": mdd, "daily_vol_pct": vol, "days": len(equity),
            "best_day_pct": round(max(rets) * 100, 2) if rets else None,
            "worst_day_pct": round(min(rets) * 100, 2) if rets else None}


def build_league():
    """순위표: 계좌별 화면 자료에서 한 줄씩 뽑아 수익률 순으로."""
    cfg, rows = config(), []
    for acct in accounts(cfg):
        f = HOME / "docs" / "data" / "accounts" / f"{acct['id']}.json"
        if not f.exists():
            continue
        st = json.loads(f.read_text(encoding="utf-8"))
        s = st["summary"]
        rows.append({"id": acct["id"], "name": acct["name"], "github": acct["github"], "agent": acct["agent"],
                     "opened": st["opened"], "asof": st["equity"][-1]["d"] if st["equity"] else None,
                     "total": s["total"], "pnl_krw": s["pnl_krw"], "pnl_pct": s["pnl_pct"], "bench_pct": s["bench_pct"],
                     "excess_pct": None if s["bench_pct"] is None else round(s["pnl_pct"] - s["bench_pct"], 2),
                     "cash_pct": s["cash_pct"], "n_positions": len(st["positions"]), "n_orders": s["n_orders"],
                     "n_filled": s["n_filled"], "fees_krw": s["fees_krw"], "integrity_ok": st["integrity"]["ok"],
                     "returns": {p["key"]: p for p in (st.get("performance") or {}).get("periods", [])},
                     "max_drawdown_pct": ((st.get("performance") or {}).get("max_drawdown") or {}).get("pct"),
                     "curve": [e["total"] for e in st["equity"]][-120:], "_equity": st["equity"], "_initial": st["initial"]})

    def ranked(items, key):                             # 수익률 순, 같으면 같은 순위
        items.sort(key=lambda r: (-(key(r) if key(r) is not None else -1e9), r["id"]))
        for i, r in enumerate(items):
            r["rank"] = items[i - 1]["rank"] if i and key(items[i - 1]) == key(r) else i + 1
        return items

    ranked(rows, lambda r: r["pnl_pct"])
    # 대회 = 이름 붙인 기간. 계좌를 새로 열지 않고, 같은 자산 곡선에서 그 기간의 수익률만 잰다.
    today, contests = now().date().isoformat(), []
    for c in (cfg.get("league") or {}).get("contests") or []:
        start, end = c.get("start"), c.get("end")
        if not start:
            continue
        entries = []
        for r in rows:
            sr = span_return(r["_equity"], r["_initial"], start, end)
            if sr:
                entries.append({"id": r["id"], "name": r["name"], "agent": r["agent"], **sr})
        contests.append({"name": c.get("name") or "대회", "start": start, "end": end,
                         "status": "예정" if today < start else ("끝남" if end and today > end else "진행 중"),
                         "players": ranked(entries, lambda r: r["pct"])})
    for r in rows:
        del r["_equity"], r["_initial"]
    out = {"name": (cfg.get("league") or {}).get("name") or "모의 거래소", "updated": now().isoformat(timespec="seconds"),
           "initial": cfg["initial_cash"], "periods": [{"key": k, "label": l} for k, l, _ in PERIODS] + [{"key": "ytd", "label": "올해"}, {"key": "all", "label": "처음부터"}],
           "players": rows, "contests": contests}
    LEAGUE_OUT.parent.mkdir(parents=True, exist_ok=True)
    LEAGUE_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ---------- 장부 ----------
def read_ledger():
    if not LEDGER.exists():
        return []
    return [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]


def _digest(rec):
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def append(kind, data):
    events = read_ledger()
    rec = {"seq": len(events) + 1, "ts": now().isoformat(timespec="seconds"), "type": kind,
           "data": data, "prev": events[-1]["hash"] if events else "0" * 64}
    rec["hash"] = _digest(rec)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def verify(events=None):
    events = read_ledger() if events is None else events
    prev = "0" * 64
    for i, e in enumerate(events, 1):
        if e["seq"] != i or e["prev"] != prev or e["hash"] != _digest(e):
            return False, i
        prev = e["hash"]
    return True, len(events)


# ---------- 돈: 비용과 반올림 ----------
# 원화는 1원, 달러는 1센트 단위. 요율은 config.json 의 "fees" (출처·기준일은 CLAUDE.md).
def won_floor(x):
    return math.floor(x + 1e-6)


def cent(x):
    return round(x + 1e-9, 2)


def cent_up(x):
    return math.ceil(x * 100 - 1e-6) / 100


def fee_cfg(cfg):
    """새 설정("fees")이 없으면 옛 방식(매매마다 fee_rate 한 가지)으로 읽는다."""
    f = cfg.get("fees")
    if f:
        return f
    r = cfg.get("fee_rate", 0)
    return {"KR": {"commission_rate": r}, "US": {"commission_rate": r}}


def buy_load(cfg, market):
    """살 때 값에 얹히는 비율 (금액 주문에서 몇 주를 살 수 있는지 셀 때 쓴다)."""
    f = fee_cfg(cfg).get(market, {})
    return f.get("commission_rate", 0) + f.get("exchange_fee_rate", 0)


def trade_costs(cfg, market, side, qty, gross, date, etf=False):
    """매매 한 건의 비용. 그 시장의 돈(한국 원, 미국 달러)으로 {"commission": 수수료, "tax": 세금·제비용}."""
    f = fee_cfg(cfg).get(market, {})
    if market == "KR":
        out = {"commission": won_floor(gross * (f.get("commission_rate", 0) + f.get("exchange_fee_rate", 0))), "tax": 0}
        if side == "sell" and not etf:                  # 증권거래세(+농어촌특별세). ETF 는 없다
            out["tax"] = won_floor(gross * f.get("sell_tax_rate", 0))
        return out
    out = {"commission": cent(gross * f.get("commission_rate", 0)), "tax": 0}
    if side == "sell":                                  # 미국 매도 제비용: SEC 비용(금액 비례) + FINRA 비용(주 수 비례, 상한)
        sec = cent_up(gross * f["sec_fee_rate"]) if f.get("sec_fee_rate") and date >= f.get("sec_fee_from", "") else 0
        taf = min(f.get("taf_max", 1e18), cent_up(qty * f["taf_per_share"])) if f.get("taf_per_share") else 0
        out["tax"] = cent(sec + taf)
    return out


def fx_spread(cfg):
    return fee_cfg(cfg).get("fx_spread_rate", 0)


# ---------- 상태 다시 만들기 ----------
def replay(events):
    st = {"cash": 0.0, "usd": 0.0, "opened": None, "initial": 0.0, "lots": {}, "orders": {}, "fills": [],
          "realized": {}, "last_buy": {}, "last_buy_ts": {}, "refused": [], "seen": set(),
          "moves": [],                # 돈·수량이 움직인 모든 일 {date, krw, usd, symbol, qty} — 자산 곡선에 쓴다
          "costs": {"commission": 0.0, "tax": 0.0, "fx": 0.0},      # 낸 비용 (원화로)
          "dividends": [], "div_by_order": {}, "splits": {}, "actions": set(), "us_gain": {}, "fx_log": [],
          "watches": {}}
    for e in events:
        t, d = e["type"], e["data"]
        if t == "open":
            st["cash"] = st["initial"] = float(d["initial_cash"])
            st["opened"] = d["opened"]
        elif t == "order":
            st["orders"][d["id"]] = {**d, "ts": e["ts"], "status": "pending", "result": None,
                                     "filled_qty": 0, "fills": []}
            if d.get("client_id"):
                st["seen"].add(d["client_id"])
        elif t == "refuse":                             # 창구로 들어온 요청을 받지 않았다
            st["refused"].append({**d, "ts": e["ts"]})
            if d.get("client_id"):
                st["seen"].add(d["client_id"])
        elif t == "cancel":
            o = st["orders"][d["order"]]
            o["status"], o["result"] = "canceled", {**(o["result"] or {}), "ts": e["ts"], "why": d["why"]}
            if d.get("client_id"):
                st["seen"].add(d["client_id"])
        elif t == "watch":                              # 값 조건 지켜보기 (주문을 내지 않고 알리기만)
            st["watches"][d["id"]] = {**d, "ts": e["ts"], "status": "watching", "result": None}
            if d.get("client_id"):
                st["seen"].add(d["client_id"])
        elif t == "unwatch":
            w = st["watches"][d["watch"]]
            w["status"], w["result"] = "removed", {"ts": e["ts"], "why": d.get("why")}
            if d.get("client_id"):
                st["seen"].add(d["client_id"])
        elif t in ("reject", "expire"):
            o = st["orders"][d["order"]]
            o["status"] = "rejected" if t == "reject" else "expired"
            o["result"] = {**(o["result"] or {}), "ts": e["ts"], "why": d["why"], "date": d.get("date")}
        elif t == "fill":
            o = st["orders"][d["order"]]
            o["fills"].append(d)
            o["filled_qty"] += d["qty"]
            o["qty_total"] = d.get("total", d["qty"])
            o["triggered"] = d.get("triggered", False)
            o["last_fill_ts"], o["last_fill_date"] = d.get("last_ts"), d["date"]
            o["status"] = "filled" if o["filled_qty"] >= o["qty_total"] else "partial"
            fs = o["fills"]
            q = sum(f["qty"] for f in fs)
            o["result"] = {**d, "ts": e["ts"], "qty": q, "price": round(sum(f["price"] * f["qty"] for f in fs) / q, 4),
                           "gross_krw": sum(f["gross_krw"] for f in fs), "fee_krw": sum(f["fee_krw"] for f in fs),
                           "pieces": sum(f.get("pieces", 1) for f in fs), "chunks": len(fs),
                           "first_at": fs[0].get("first_at") or fs[0].get("at"), "total": o["qty_total"]}
            if any("fees" in f for f in fs):
                o["result"]["fees"] = {k: round(sum((f.get("fees") or {}).get(k, 0) for f in fs), 2) for k in ("commission", "tax")}
                o["result"]["gross"] = round(sum(f.get("gross", 0) for f in fs), 2)
            # 돈: 옛 줄(ccy 없음)은 원화 한 주머니, 새 줄은 그 시장의 돈(delta)으로 움직인다
            usd = d.get("ccy") == "USD"
            amt = d["delta"] if "delta" in d else d["cash_delta"]
            rate = d.get("fx") or 1.0 if usd else 1.0
            if usd:
                st["usd"] = round(st["usd"] + amt, 2)
            else:
                st["cash"] += amt
            fees = d.get("fees")
            if fees:
                st["costs"]["commission"] += fees.get("commission", 0) * rate
                st["costs"]["tax"] += fees.get("tax", 0) * rate
            else:
                st["costs"]["commission"] += d.get("fee_krw", 0)
            st["fills"].append({**d, "ts": e["ts"]})
            st["moves"].append({"date": d["date"], "krw": 0 if usd else amt, "usd": amt if usd else 0,
                                "symbol": d["symbol"], "qty": d["qty"] if d["side"] == "buy" else -d["qty"]})
            lots = st["lots"].setdefault(d["symbol"], [])
            if d["side"] == "buy":                      # 산 주문마다 한 묶음 — 팔 때 먼저 산 것부터 줄인다
                lots.append({"order": d["order"], "qty": d["qty"], "cost_krw": -amt * rate,
                             "unit_local": d["price"], "date": d["date"]})
                st["last_buy"][d["symbol"]] = d["date"]
                st["last_buy_ts"][d["symbol"]] = d.get("last_ts")
            else:
                left, net = d["qty"], amt * rate
                per_share = net / d["qty"]
                while left > 0 and lots:
                    lot = lots[0]
                    take = min(left, lot["qty"])
                    cost = lot["cost_krw"] * take / lot["qty"]
                    gain = per_share * take - cost
                    st["realized"][lot["order"]] = st["realized"].get(lot["order"], 0.0) + gain
                    if d.get("market") == "US":         # 해외 주식 양도소득세 어림용 (해마다)
                        st["us_gain"][d["date"][:4]] = st["us_gain"].get(d["date"][:4], 0.0) + gain
                    lot["qty"] -= take
                    lot["cost_krw"] -= cost
                    left -= take
                    if lot["qty"] == 0:
                        lots.pop(0)
        elif t == "fx":                                 # 환전 (주문으로 냈거나, 미국 주식을 살 때 모자라서 자동으로)
            sgn = 1 if d["side"] == "buy" else -1
            st["usd"] = round(st["usd"] + sgn * d["usd"], 2)
            st["cash"] -= sgn * d["krw"]
            st["costs"]["fx"] += d.get("cost_krw", 0)
            st["moves"].append({"date": d["date"], "krw": -sgn * d["krw"], "usd": sgn * d["usd"], "symbol": None, "qty": 0})
            st["fx_log"].append({**d, "ts": e["ts"]})
            if d.get("order"):
                o = st["orders"][d["order"]]
                o["status"], o["filled_qty"] = "filled", d["usd"]
                o["result"] = {**d, "ts": e["ts"], "qty": d["usd"], "total": d["usd"], "price": d["rate"], "fx": d["mid"],
                               "gross_krw": d["krw"], "fee_krw": d.get("cost_krw", 0), "pieces": 1, "chunks": 1,
                               "first_at": d.get("at"), "cash_after": d.get("krw_after")}
        elif t == "dividend":                           # 배당이 세금을 떼고 예수금으로 들어왔다
            usd = d.get("ccy") == "USD"
            if usd:
                st["usd"] = round(st["usd"] + d["net"], 2)
            else:
                st["cash"] += d["net"]
            st["moves"].append({"date": e["ts"][:10], "krw": 0 if usd else d["net"], "usd": d["net"] if usd else 0,
                                "symbol": None, "qty": 0})
            st["dividends"].append({**d, "ts": e["ts"]})
            st["actions"].add(("dividend", d["symbol"], d["ex_date"]))
            lots = [l for l in st["lots"].get(d["symbol"], []) if l["date"] < d["ex_date"]]
            q = sum(l["qty"] for l in lots)
            for l in lots:                              # 산 주문별로 나눠 적는다 (이미 판 묶음 몫은 빠진다)
                st["div_by_order"][l["order"]] = st["div_by_order"].get(l["order"], 0.0) + (d.get("net_krw") or 0) * l["qty"] / q
        elif t == "split":                              # 액면분할·병합: 그 전에 산 묶음의 수량이 바뀐다 (원가는 그대로)
            st["actions"].add(("split", d["symbol"], d["date"]))
            st["splits"].setdefault(d["symbol"], []).append((d["date"], d["num"] / d["den"]))
            lots = [l for l in st["lots"].get(d["symbol"], []) if l["date"] < d["date"]]
            r = d["num"] / d["den"]
            if lots:
                raw = [l["qty"] * r for l in lots]
                new = [math.floor(x + 1e-9) for x in raw]
                spare = d["qty_after"] - sum(new)       # 1주 미만 자투리를 모아 생긴 주식은 자투리가 큰 묶음부터
                for i in sorted(range(len(lots)), key=lambda i: new[i] - raw[i])[:max(0, spare)]:
                    new[i] += 1
                for l, n in zip(lots, new):
                    l["qty"], l["unit_local"] = n, l["unit_local"] / r
                st["lots"][d["symbol"]] = [l for l in st["lots"][d["symbol"]] if l["qty"] > 0]
            cash = d.get("cash") or 0                   # 1주가 안 되는 자투리는 돈으로 받는다 (그만큼 주식 수에서 빠진다)
            usd = d.get("ccy") == "USD"
            if usd:
                st["usd"] = round(st["usd"] + cash, 2)
            else:
                st["cash"] += cash
            st["moves"].append({"date": d["date"], "krw": 0 if usd else cash, "usd": cash if usd else 0,
                                "symbol": d["symbol"], "qty": d["qty_after"] - d["qty_before"] * r})
        # 그 밖의 줄(옛 장부의 결정·보고 등)은 거래소가 읽지 않는다
    return st


def held(st, sym):
    return sum(l["qty"] for l in st["lots"].get(sym, []))


def split_adj(st, sym, date):
    """date 에 가진 1주가 지금 몇 주인가 (그 뒤에 장부에 적힌 분할·병합을 곱한 값). 시세가 분할 뒤 기준으로 고쳐지므로 필요하다."""
    r = 1.0
    for d, ratio in st["splits"].get(sym, []):
        if d > date:
            r *= ratio
    return r


def qty_before(st, sym, date):
    """date 전날까지 들고 있던 수량 (지금 주식 수 기준)."""
    return sum(m["qty"] * split_adj(st, sym, m["date"]) for m in st["moves"] if m["symbol"] == sym and m["date"] < date)


# ---------- 체결 ----------
OPEN = ("pending", "partial")          # 아직 살아 있는 주문


def kst_iso(ts):
    return datetime.fromtimestamp(ts, KST).isoformat(timespec="minutes") if ts else None


def _day_ts(d, hour):
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=KST).timestamp() + hour * 3600


def action_ts(market, d):
    """배당락·분할이 그날 장이 열리기 전에 일어난 것으로 보는 시각. 한국은 그날 0시, 미국은 한국 시각 13시
    (앞 날 장후가 끝난 뒤, 그날 장전이 열리기 전)."""
    return _day_ts(d, 0 if market == "KR" else 13)


def pending_actions(st):
    """시세 캐시에 있는데 아직 장부에 없는 배당·분할 가운데 이 계좌에 해당하는 것. 시각 순."""
    out, t_now = [], now().timestamp()
    opened = st["opened"] or ""
    for sym in sorted({m["symbol"] for m in st["moves"] if m["symbol"]} |
                      {o["symbol"] for o in st["orders"].values() if o["status"] in OPEN and o.get("market") != "FX"}):
        c = px.load(HOME, sym)
        ev = (c or {}).get("events") or {}
        mkt = px.market_of(sym)
        for d, (num, den) in sorted((ev.get("splits") or {}).items()):
            ts = action_ts(mkt, d)
            if d < opened or ts > t_now or ("split", sym, d) in st["actions"]:
                continue
            q = sum(l["qty"] for l in st["lots"].get(sym, []) if l["date"] < d)
            stale = [o["id"] for o in st["orders"].values() if o["status"] in OPEN and o["symbol"] == sym
                     and datetime.fromisoformat(o["ts"]).timestamp() < ts]
            if q or stale:
                out.append({"ts": ts, "kind": "split", "symbol": sym, "market": mkt, "date": d, "num": num, "den": den,
                            "qty": q, "stale": stale, "cache": c})
        for d, amount in sorted((ev.get("dividends") or {}).items()):
            ts = action_ts(mkt, d)
            if d < opened or ts > t_now or ("dividend", sym, d) in st["actions"]:
                continue
            q = math.floor(qty_before(st, sym, d) + 1e-6)
            if q >= 1:
                out.append({"ts": ts, "kind": "dividend", "symbol": sym, "market": mkt, "date": d, "amount": amount, "qty": q})
    return sorted(out, key=lambda a: (a["ts"], a["kind"] != "split", a["symbol"]))


def apply_action(a, st, cfg):
    """배당·분할 하나를 장부에 적는다."""
    sym, mkt = a["symbol"], a["market"]
    usd = mkt == "US"
    ccy = "USD" if usd else "KRW"
    if a["kind"] == "split":
        out = []
        for oid in a["stale"]:                          # 값의 기준이 바뀌므로 걸려 있던 주문은 거둔다 (실제 증권사도 그렇다)
            out.append(append("cancel", {"order": oid, "why": "액면분할·병합으로 값의 기준이 바뀌어 주문을 거두었습니다. 새 값에 맞춰 다시 내 주세요."}))
        r = a["num"] / a["den"]
        exact = a["qty"] * r
        after = math.floor(exact + 1e-9)
        bar = px.close_on_or_before(a["cache"], a["date"])
        frac = exact - after
        cash = 0
        if frac > 1e-9 and bar:
            cash = cent(frac * bar["c"]) if usd else won_floor(frac * bar["c"])
        out.append(append("split", {"symbol": sym, "market": mkt, "date": a["date"], "num": a["num"], "den": a["den"],
                                    "qty_before": a["qty"], "qty_after": after, "cash": cash, "ccy": ccy}))
        return out
    rate_tax = (fee_cfg(cfg).get("dividend_tax") or {}).get(mkt, 0)
    gross = a["qty"] * a["amount"]
    gross = cent(gross) if usd else won_floor(gross)
    tax = cent(gross * rate_tax) if usd else won_floor(gross * rate_tax)
    net = cent(gross - tax) if usd else gross - tax
    fx = px.fx_at(HOME, now().timestamp(), px.load(HOME, px.FX_KEY))[0] if usd else 1.0
    return [append("dividend", {
        "symbol": sym, "market": mkt, "ex_date": a["date"], "per_share": a["amount"], "qty": a["qty"], "ccy": ccy,
        "gross": gross, "tax": tax, "tax_rate": rate_tax, "net": net, "fx": fx,
        "gross_krw": round(gross * fx) if fx else None, "tax_krw": round(tax * fx) if fx else None,
        "net_krw": round(net * fx) if fx else None,
        "cash_after": round(st["cash"] + (0 if usd else net)), "usd_after": round(st["usd"] + (net if usd else 0), 2)})]


def fx_event(o, today):
    """환전 주문의 다음 사건. 주문 뒤에 시작한 1분 환율의 시작 값으로 바꾼다. 1분 환율이 없으면 다음 날 하루 환율의 시작 값."""
    start = datetime.fromisoformat(o["ts"]).timestamp()
    d0 = datetime.fromtimestamp(start - 86400, KST).strftime("%Y-%m-%d")
    for d in px.minute_dates(HOME, px.FX_KEY):
        if d < d0:
            continue
        for b in px.load_minutes(HOME, px.FX_KEY, d)["bars"]:
            if b[0] >= start:
                return ("fill", {"sort_ts": b[0], "ts": b[0], "mid": b[1], "precision": "1분",
                                 "date": datetime.fromtimestamp(b[0], KST).strftime("%Y-%m-%d")})
    daily = px.load(HOME, px.FX_KEY)
    placed = datetime.fromisoformat(o["ts"]).astimezone(KST).strftime("%Y-%m-%d")
    for b in (daily["bars"] if daily else []):
        if placed < b["d"] <= o["valid_until"]:
            return ("fill", {"sort_ts": _day_ts(b["d"], 9), "ts": None, "mid": b["o"], "precision": "하루", "date": b["d"]})
    if today > o["valid_until"]:
        return ("expire", f"유효기간({o['valid_until']})까지 환율을 받지 못함")
    return None


def fill_fx(o, f, st, cfg):
    """환전 주문 체결. 살 때는 기준 환율보다 비싸게, 팔 때는 싸게 (그 차이가 환전 비용)."""
    s, mid = fx_spread(cfg), f["mid"]
    if o["side"] == "buy":
        rate = mid * (1 + s)
        usd = float(o["usd"]) if o.get("usd") else math.floor(o["krw"] / rate * 100 + 1e-6) / 100
        krw = math.ceil(usd * rate - 1e-6)
        if usd < 0.01:
            return append("reject", {"order": o["id"], "why": "환전 금액이 1센트보다 작음"})
        if krw > st["cash"] + 0.5:
            return append("reject", {"order": o["id"], "date": f["date"],
                                     "why": f"원화 예수금 부족 — 필요 {krw:,}원, 보유 {round(st['cash']):,}원"})
    else:
        rate = mid * (1 - s)
        usd = st["usd"] if o.get("usd") in (None, "all") else float(o["usd"])
        if usd < 0.01 or usd > st["usd"] + 0.005:
            return append("reject", {"order": o["id"], "date": f["date"],
                                     "why": f"달러 예수금 부족 — 주문 {usd:,.2f}달러, 보유 {st['usd']:,.2f}달러"})
        krw = won_floor(usd * rate)
    sgn = 1 if o["side"] == "buy" else -1
    return append("fx", {"order": o["id"], "ref": o.get("ref", ""), "side": o["side"], "usd": round(usd, 2),
                         "mid": mid, "rate": round(rate, 4), "krw": krw, "cost_krw": round(usd * mid * s),
                         "date": f["date"], "at": kst_iso(f["ts"]), "last_ts": f["ts"], "precision": f["precision"],
                         "krw_after": round(st["cash"] - sgn * krw), "usd_after": round(st["usd"] + sgn * usd, 2)})


def settle():
    """살아 있는 주문과 배당·분할을 시간 순서대로 처리한다. 계산은 matching.py, 여기서는 돈·수량 확인과 장부 기록."""
    cfg = config()
    spread = fx_spread(cfg)
    today = now().date().isoformat()
    done = []
    while True:
        st = replay(read_ledger())
        live = [o for o in st["orders"].values() if o["status"] in OPEN]
        acts = pending_actions(st)
        if not live and not acts:
            break
        # 분할·병합은 언제나 먼저: 시세 원천이 지난 값까지 새 기준으로 고쳐 주므로, 옛 기준으로 걸어 둔 주문을 그 시세에 대 보면 안 된다
        splits = [x for x in acts if x["kind"] == "split"]
        if splits:
            done += apply_action(splits[0], st, cfg)
            continue
        fx_daily = px.load(HOME, px.FX_KEY)

        def rate_at(market, ts):
            if market != "US":
                return 1.0
            return px.fx_at(HOME, ts, fx_daily)[0]

        best = None
        for o in live:
            sym = o["symbol"]
            if o["market"] == "FX":
                ev = fx_event(o, today)
            else:
                def size_fn(price, ts, o=o):
                    r = rate_at(o["market"], ts)
                    if o["market"] == "US" and r:
                        r *= 1 + spread                 # 금액 주문은 전부 환전해서 산다고 보고 넉넉히 잡는다
                    return math.floor(o["krw"] / (price * r * (1 + buy_load(cfg, o["market"])))) if r else 0

                ctx = {"daily": px.load(HOME, sym), "minutes": lambda d, sym=sym: px.load_minutes(HOME, sym, d),
                       "minute_dates": px.minute_dates(HOME, sym), "held": held(st, sym),
                       "pending_buy": any(x["status"] in OPEN and x["symbol"] == sym and x["side"] == "buy"
                                          for x in st["orders"].values()),
                       "last_buy_ts": st["last_buy_ts"].get(sym), "last_buy_date": st["last_buy"].get(sym),
                       "size_fn": size_fn, "cfg": cfg, "today": today,
                       "ext_cap_fn": lambda price, ts, o=o: math.floor(
                           cfg.get("ext_max_krw_per_min", 0) / (price * (rate_at(o["market"], ts) or 1e18)))}
                ev = mt.next_event(o, ctx)
            if ev is None:
                continue
            if ev[0] in ("expire", "reject"):
                best = ((0, o["id"]), o, ev)
                break
            key = (ev[1]["sort_ts"], o["id"])
            if best is None or key < best[0]:
                best = (key, o, ev)
        # 배당·분할이 다음 체결보다 먼저(같은 시각 포함)면 그것부터
        if acts and (best is None or (best[2][0] == "fill" and acts[0]["ts"] <= best[0][0])):
            done += apply_action(acts[0], st, cfg)
            continue
        if best is None:
            break
        _, o, ev = best
        if ev[0] == "expire":
            done.append(append("expire", {"order": o["id"], "why": ev[1]}))
            continue
        if ev[0] == "reject":
            why = ev[1]
            if why == "too_small":
                r = rate_at(o["market"], ev[2]["ts"]) or 0
                why = f"주문 금액이 1주 값({round(ev[2]['price'] * r):,}원)보다 작음"
            done.append(append("reject", {"order": o["id"], "why": why}))
            continue
        f = ev[1]
        if o["market"] == "FX":
            done.append(fill_fx(o, f, st, cfg))
            continue
        ts = f["last_ts"] or f["sort_ts"]
        rate = rate_at(o["market"], ts)
        if rate is None:
            break                                       # 환율이 아직 없다 — 다음 실행에서
        usd = o["market"] == "US"
        gross = cent(f["qty"] * f["price"]) if usd else round(f["qty"] * f["price"])
        etf = ((px.load(HOME, o["symbol"]) or {}).get("kind") == "etf")
        fees = trade_costs(cfg, o["market"], o["side"], f["qty"], gross, f["date"], etf)
        fee = fees["commission"] + fees["tax"]
        krw_bal, usd_bal = st["cash"], st["usd"]
        if o["side"] == "buy":
            need = cent(gross + fee) if usd else gross + fee
            if usd and need > usd_bal + 0.005:          # 달러가 모자란다
                short = cent(need - usd_bal)
                krw_need = math.ceil(short * rate * (1 + spread) - 1e-6)
                if cfg.get("usd_shortfall", "auto") != "auto":
                    done.append(append("reject", {"order": o["id"], "date": f["date"],
                                                  "why": f"달러 예수금 부족 — 필요 {need:,.2f}달러, 보유 {usd_bal:,.2f}달러"}))
                    continue
                if krw_need > krw_bal + 0.5:
                    done.append(append("reject", {"order": o["id"], "date": f["date"],
                                                  "why": f"현금 부족 — 필요 {krw_need:,}원(모자란 {short:,.2f}달러 환전), 보유 {round(krw_bal):,}원"}))
                    continue
                krw_bal, usd_bal = krw_bal - krw_need, round(usd_bal + short, 2)
                done.append(append("fx", {"order": None, "for": o["id"], "auto": True, "side": "buy", "usd": short,
                                          "mid": rate, "rate": round(rate * (1 + spread), 4), "krw": krw_need,
                                          "cost_krw": round(short * rate * spread), "date": f["date"],
                                          "at": kst_iso(f["last_ts"]), "last_ts": f["last_ts"], "precision": f["precision"],
                                          "krw_after": round(krw_bal), "usd_after": usd_bal}))
            elif not usd and need > krw_bal + 0.5:
                done.append(append("reject", {"order": o["id"], "date": f["date"],
                                              "why": f"현금 부족 — 필요 {round(need):,}원, 보유 {round(krw_bal):,}원"}))
                continue
            delta = -need
        else:
            delta = cent(gross - fee) if usd else gross - fee
        if usd:
            usd_bal = round(usd_bal + delta, 2)
        else:
            krw_bal += delta
        done.append(append("fill", {
            "order": o["id"], "ref": o.get("ref", ""), "symbol": o["symbol"], "market": o["market"],
            "side": o["side"], "date": f["date"], "price": f["price"], "fx": rate, "qty": f["qty"],
            "total": f["total"], "remaining": f["total"] - o["filled_qty"] - f["qty"],
            "at": kst_iso(f["last_ts"]), "first_at": kst_iso(f["first_ts"]), "last_ts": f["last_ts"],
            "precision": f["precision"], "pieces": f["pieces"], "triggered": f["triggered"],
            "session": f.get("session") or "r",
            "ccy": "USD" if usd else "KRW", "gross": gross, "fees": fees, "delta": delta, "etf": etf,
            "gross_krw": round(gross * rate), "fee_krw": round(fee * rate), "cash_delta": round(delta * rate),
            "cash_after": round(krw_bal), "usd_after": usd_bal}))
    return done


# ---------- 화면 자료 ----------
def needed_keys(st, cfg):
    keys = {b["symbol"] for b in cfg["benchmark"]} | {px.FX_KEY}
    keys |= {s for s, l in st["lots"].items() if l}
    keys |= {o["symbol"] for o in st["orders"].values()}
    keys |= {m["symbol"] for m in st["moves"] if m["symbol"]}      # 판 뒤에 확인되는 배당도 있다
    keys |= {w["symbol"] for w in st["watches"].values() if w["status"] == "watching"}
    return sorted(keys)


def build():
    cfg = config()
    events = read_ledger()
    ok, n = verify(events)
    st = replay(events)
    keys = needed_keys(st, cfg)
    caches = {k: px.load(HOME, k) for k in keys}
    fx = caches.get(px.FX_KEY)
    today = now().date().isoformat()

    def krw(sym, date):
        c = caches.get(sym)
        b = px.close_on_or_before(c, date)
        if not b:
            return None, None
        rate = 1.0
        if px.market_of(sym) == "US":
            f = px.close_on_or_before(fx, date)
            if not f:
                return None, None
            rate = f["c"]
        return b["c"] * rate, b

    def name(sym):
        if sym == px.FX_KEY:
            return "달러 환전"
        c = caches.get(sym)
        return c["name"] if c else sym

    fx_bar = px.close_on_or_before(fx, today)
    fx_now = fx_bar["c"] if fx_bar else (st["fx_log"][-1]["mid"] if st["fx_log"] else None)
    usd_krw = st["usd"] * fx_now if fx_now else 0.0      # 달러 예수금의 원화 값어치 (오늘 환율)
    cash_all = st["cash"] + usd_krw

    # 보유 종목
    positions, invested = [], 0.0
    for sym, lots in st["lots"].items():
        q = sum(l["qty"] for l in lots)
        if q == 0:
            continue
        cost = sum(l["cost_krw"] for l in lots)
        unit, bar = krw(sym, today)
        value = q * unit if unit else cost
        invested += value
        ext = px.last_trade(HOME, sym)
        if ext and bar and ext["session"] != "r" and datetime.fromtimestamp(ext["ts"], KST).strftime("%Y-%m-%d") >= bar["d"]:
            rate = px.fx_at(HOME, ext["ts"], fx)[0] if px.market_of(sym) == "US" else 1.0
            ext = {**ext, "value_krw": round(q * ext["price"] * rate) if rate else None,
                   "at": datetime.fromtimestamp(ext["ts"], KST).isoformat(timespec="minutes"),
                   "chg_pct": round((ext["price"] / bar["c"] - 1) * 100, 2)}
        else:
            ext = None
        positions.append({"symbol": sym, "name": name(sym), "market": px.market_of(sym), "qty": q, "ext": ext,
                          "avg_cost_krw": round(cost / q), "price": bar["c"] if bar else None,
                          "price_date": bar["d"] if bar else None,
                          "currency": "USD" if px.market_of(sym) == "US" else "KRW",
                          "value_krw": round(value), "cost_krw": round(cost),
                          "pnl_krw": round(value - cost), "pnl_pct": round((value / cost - 1) * 100, 2) if cost else 0,
                          "orders": sorted({l["order"] for l in lots})})
    total = cash_all + invested
    for p in positions:
        p["weight"] = round(p["value_krw"] / total * 100, 1) if total else 0
    positions.sort(key=lambda p: -p["value_krw"])

    # 자산 곡선과 비교 기준
    opened = st["opened"] or cfg["opened"]
    dates = {opened}
    for k in keys:
        if k != px.FX_KEY and caches.get(k):
            dates |= {b["d"] for b in caches[k]["bars"] if b["d"] >= opened}
    base = {}
    for b in cfg["benchmark"]:
        base[b["symbol"]] = krw(b["symbol"], opened)[0]
    equity = []
    last_d = max(dates)
    for d in sorted(dates):
        cash, usd, qty = st["initial"], 0.0, {}
        for m in st["moves"]:
            if m["date"] <= d or d == last_d:           # 마지막 점은 지금 상태 (시세 기준일 뒤에 생긴 환전·배당 포함)
                cash += m["krw"]
                usd += m["usd"]
                if m["symbol"]:                         # 시세가 분할 뒤 기준이므로 수량도 지금 주식 수로 센다
                    qty[m["symbol"]] = qty.get(m["symbol"], 0) + m["qty"] * split_adj(st, m["symbol"], m["date"])
        if abs(usd) >= 0.005:
            f = px.close_on_or_before(fx, d)
            cash += usd * (f["c"] if f else (fx_now or 0))
        val = 0.0
        for s, q in qty.items():
            u = krw(s, d)[0]
            val += q * u if u else 0
        bench = None
        if all(base.values()):
            ratio = 0.0
            for b in cfg["benchmark"]:
                u = krw(b["symbol"], d)[0]
                ratio += b["weight"] * (u / base[b["symbol"]] if u else 1)
            bench = round(st["initial"] * ratio)
        equity.append({"d": d, "total": round(cash + val), "cash": round(cash), "bench": bench})
    last = equity[-1] if equity else {"total": total, "bench": None}

    # 산 주문별 손익 (실현 + 미실현) — 운용 일지가 이것을 결정 기록과 맞춰 본다
    unreal = {}
    for sym, lots in st["lots"].items():
        unit = krw(sym, today)[0]
        for l in lots:
            if l["qty"] and unit:
                unreal[l["order"]] = unreal.get(l["order"], 0.0) + l["qty"] * unit - l["cost_krw"]
    order_pnl = {}
    for o in st["orders"].values():
        if o["side"] == "buy" and o["filled_qty"]:
            r, u = st["realized"].get(o["id"], 0.0), unreal.get(o["id"], 0.0)
            order_pnl[o["id"]] = {"realized_krw": round(r), "unrealized_krw": round(u), "total_krw": round(r + u),
                                  "dividend_krw": round(st["div_by_order"].get(o["id"], 0.0))}

    t_now = now()
    orders = []
    for o in st["orders"].values():
        o = {**o, "name": name(o["symbol"]) if name(o["symbol"]) != o["symbol"] else (o.get("name") or o["symbol"])}
        if o["status"] in OPEN:                        # 가장 빨리 체결될 수 있는 때 (접수 시각과 지금 중 늦은 쪽 뒤의 첫 1분)
            base = max(datetime.fromisoformat(o["ts"]), t_now)
            ef = mk.earliest_fill(o, base)
            o["earliest_fill"] = ef.isoformat(timespec="minutes") if ef else None
        orders.append(o)

    # 지켜보는 조건 (주문을 내지 않고 알리기만)
    watches = []
    for w in st["watches"].values():
        status, hit = watch_result(w, today)
        watches.append({k: w.get(k) for k in ("id", "ref", "symbol", "name", "market", "when", "value", "valid_until",
                                               "client_id", "requested_at", "ts")}
                       | {"status": status, "hit": hit, "text": WATCH_WHEN[w["when"]].format(v=format(w["value"], ",g")),
                          "removed": w["result"]})
    watches.sort(key=lambda w: w["id"], reverse=True)

    # 운용자가 주문 전에 볼 값 — 보유·대기·지켜보는 종목 (거래소가 가진 마지막 값, 원천에 다시 묻지 않는다)
    qsyms = {p_["symbol"] for p_ in positions} | {o["symbol"] for o in orders if o["status"] in OPEN and o["symbol"] != px.FX_KEY} \
        | {w["symbol"] for w in watches if w["status"] == "watching"}
    quotes = {q: quote(q, cache=caches.get(q)) for q in sorted(qsyms)}

    # 흐름(최근 것부터)
    feed = []
    for e in reversed(events):
        t, d = e["type"], e["data"]
        if t == "open":
            txt = f"계좌를 열었습니다. 시작 금액 {int(d['initial_cash']):,}원."
        elif t == "order" and d.get("market") == "FX":
            if d["side"] == "buy":
                amt = f"{int(d['krw']):,}원을 달러로" if d.get("krw") else f"{d['usd']:,.2f}달러 사기"
            else:
                amt = "달러 전부를 원화로" if d.get("usd") in (None, "all") else f"{d['usd']:,.2f}달러를 원화로"
            txt = f"주문 {d['id']} — 환전 {amt}"
        elif t == "order":
            how = {"market": "시장가", "moc": "종가"}.get(d["type"]) or f"{'지정가' if d['type'] == 'limit' else '손절가'} {d['price']:,}"
            if d.get("session") == "all":
                how += ", 시간외 포함"
            amt = f"{int(d['krw']):,}원어치" if d.get("krw") else ("전량" if d.get("qty") in (None, "all") else f"{d['qty']}주")
            txt = f"주문 {d['id']} — {name(d['symbol'])} {'사기' if d['side'] == 'buy' else '팔기'} {amt} ({how})"
        elif t == "fill":
            when = (d.get("at") or d["date"]).replace("T", " ")[:16]
            if d.get("session") in ("pre", "post"):
                when += " " + px.SESSION_KO[d["session"]]
            part = f" (주문 {d['total']}주 중, 남은 {d['remaining']}주)" if d.get("remaining") else ""
            fees = d.get("fees")
            if fees and d.get("ccy") == "USD":
                cost = f"수수료 {fees['commission']:,.2f}달러" + (f", 매도 제비용 {fees['tax']:,.2f}달러" if fees.get("tax") else "")
                money = f"금액 {d['gross']:,.2f}달러({d['gross_krw']:,}원)"
            elif fees:
                cost = f"수수료 {fees['commission']:,}원" + (f", 거래세 {fees['tax']:,}원" if fees.get("tax") else "")
                money = f"금액 {d['gross_krw']:,}원"
            else:
                cost, money = f"비용 {d['fee_krw']:,}원", f"금액 {d['gross_krw']:,}원"
            txt = (f"체결 {d['order']} — {name(d['symbol'])} {d['qty']}주 {'샀습니다' if d['side'] == 'buy' else '팔았습니다'}{part}. "
                   f"{when} 가격 {d['price']:,}, {money}, {cost}.")
        elif t == "fx":
            when = (d.get("at") or d["date"]).replace("T", " ")[:16]
            head = f"환전 {d['order']}" if d.get("order") else f"자동 환전({d.get('for')} 매수에 모자란 달러)"
            way = (f"{d['krw']:,}원 → {d['usd']:,.2f}달러" if d["side"] == "buy" else f"{d['usd']:,.2f}달러 → {d['krw']:,}원")
            txt = f"{head} — {way}. {when} 기준 환율 {d['mid']:,.2f}원, 적용 {d['rate']:,.2f}원, 환전 비용 {d.get('cost_krw', 0):,}원."
        elif t == "dividend":
            unit = "달러" if d.get("ccy") == "USD" else "원"
            n = (lambda v: f"{v:,.2f}") if d.get("ccy") == "USD" else (lambda v: f"{v:,}")
            txt = (f"배당 — {name(d['symbol'])} {d['qty']}주 × 주당 {d['per_share']:,}{unit} = {n(d['gross'])}{unit}. "
                   f"세금 {n(d['tax'])}{unit}({d['tax_rate'] * 100:g}%)을 떼고 {n(d['net'])}{unit}이 예수금으로 들어왔습니다. 배당락일 {d['ex_date']}.")
        elif t == "split":
            kind = "액면분할" if d["num"] > d["den"] else "주식 병합"
            txt = f"{kind} — {name(d['symbol'])} {d['den']:g}주가 {d['num']:g}주로. 보유 {d['qty_before']}주 → {d['qty_after']}주 (산 값 총액은 그대로)."
            if d.get("cash"):
                txt += f" 1주가 안 되는 자투리는 {d['cash']:,}{'달러' if d.get('ccy') == 'USD' else '원'}으로 받았습니다."
        elif t == "reject":
            txt = f"거부 {d['order']} — {d['why']}"
        elif t == "expire":
            txt = f"만료 {d['order']} — {d['why']}"
        elif t == "cancel":
            txt = f"취소 {d['order']} — {d['why']}"
        elif t == "refuse":
            txt = f"주문 요청을 받지 않았습니다 — {d['why']}"
        elif t == "watch":
            cond = WATCH_WHEN[d["when"]].format(v=format(d["value"], ",g"))
            txt = f"지켜보기 {d['id']} — {d.get('name') or d['symbol']}: {cond} (~{d['valid_until']})"
        elif t == "unwatch":
            txt = f"지켜보기 {d['watch']} 를 거뒀습니다 — {d.get('why') or ''}"
        else:
            continue
        feed.append({"seq": e["seq"], "ts": e["ts"], "type": t, "text": txt})

    asof = {k: (caches[k]["bars"][-1]["d"] if caches.get(k) and caches[k]["bars"] else None) for k in keys}
    costs = {k + "_krw": round(v) for k, v in st["costs"].items()}
    divs = [{**d, "name": name(d["symbol"])} for d in reversed(st["dividends"])]
    fc = fee_cfg(cfg)
    year = today[:4]
    gt = fc.get("us_gains_tax")
    gain = st["us_gain"].get(year, 0.0)
    us_gains = None
    if gt:                                              # 떼지 않고 보여 주기만 하는 어림 (사용자 결정 2026-11-14)
        us_gains = {"year": year, "realized_krw": round(gain), "deduction_krw": gt["deduction_krw"], "rate": gt["rate"],
                    "est_tax_krw": round(max(0.0, gain - gt["deduction_krw"]) * gt["rate"])}
    out = {
        "account": account_label(cfg), "updated": now().isoformat(timespec="seconds"),
        "player": {k: ACCT[k] for k in ("id", "github", "name", "agent")},
        "opened": opened, "initial": st["initial"], "fee_rate": fc.get("KR", {}).get("commission_rate", cfg.get("fee_rate", 0)),
        "fees": fc,
        "rules": cfg["rules"],
        "benchmark": [{**b, "name": name(b["symbol"])} for b in cfg["benchmark"]],
        "summary": {
            "total": round(last["total"]), "cash": round(cash_all), "invested": round(invested),
            "cash_pct": round(cash_all / total * 100, 1) if total else 100,
            "cash_krw": round(st["cash"]), "cash_usd": round(st["usd"], 2), "cash_usd_krw": round(usd_krw),
            "ext_delta_krw": sum(p["ext"]["value_krw"] - p["value_krw"] for p in positions
                                 if p.get("ext") and p["ext"].get("value_krw") is not None),
            "pnl_krw": round(last["total"] - st["initial"]),
            "pnl_pct": round((last["total"] / st["initial"] - 1) * 100, 2) if st["initial"] else 0,
            "bench_pct": round((last["bench"] / st["initial"] - 1) * 100, 2) if last.get("bench") else None,
            "fees_krw": sum(costs.values()), "costs": costs,
            "dividends": {"count": len(divs), "gross_krw": sum(d.get("gross_krw") or 0 for d in divs),
                          "tax_krw": sum(d.get("tax_krw") or 0 for d in divs),
                          "net_krw": sum(d.get("net_krw") or 0 for d in divs)},
            "us_gains": us_gains,
            "n_orders": len(orders), "n_filled": sum(o["status"] == "filled" for o in orders),
            "n_pending": sum(o["status"] in OPEN for o in orders),
        },
        "performance": performance(equity, st["initial"]),
        "positions": positions, "equity": equity,
        "orders": sorted(orders, key=lambda o: o["id"], reverse=True),
        "order_pnl": order_pnl,
        "dividends": divs,
        "refused": list(reversed(st["refused"])),
        "feed": feed[:300],
        "integrity": {"ok": ok, "lines": len(events), "head": events[-1]["hash"][:12] if events else None,
                      "broken_at": None if ok else n},
        "prices_asof": asof,
        "fx": fx_now,
        "markets": {m: mk.status(m, t_now) for m in ("KR", "US", "FX")},
        "next_run": {"exchange": mk.next_cron(t_now).isoformat(timespec="minutes"),
                     "note": "매시 7분 정기 실행 (GitHub 예약은 몇 분~몇십 분 늦을 수 있다). 주문·취소 요청은 올라오면 1분 안팎에 따로 접수된다."},
        "calendar": {"source": "holidays 0.108 의 KRX·NYSE 달력 (broker/markets.py)", "until": f"{max(mk.CAL_YEARS)}-12-31",
                     "missing": "임시공휴일, 수능일·새해 첫날의 늦은 개장"},
        "quotes": quotes,
        "watches": watches,
        "watch_hits": [w for w in watches if w["status"] == "hit"],
    }
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if ACCT["main"]:                                    # 주인 계좌도 다른 계좌와 같은 자리에서 읽을 수 있게 한 벌 더
        twin = HOME / "docs" / "data" / "accounts" / f"{ACCT['id']}.json"
        twin.parent.mkdir(parents=True, exist_ok=True)
        twin.write_text(STATE_OUT.read_text(encoding="utf-8"), encoding="utf-8")
    return out


# ---------- 명령 ----------
def need_open(st):
    if st["opened"] is None:
        sys.exit("계좌가 없습니다. 먼저: python broker/broker.py open")


def cmd_open(a):
    if read_ledger():
        sys.exit("이미 열린 계좌입니다.")
    cfg = config()
    append("open", {"account": account_label(cfg), "player": ACCT["github"], "initial_cash": cfg["initial_cash"],
                    "opened": now().date().isoformat(), "fees": fee_cfg(cfg), "rules": cfg["rules"]})
    print(f"계좌 개설: {account_label(cfg)} · {cfg['initial_cash']:,}원")


class Refused(Exception):
    """주문을 받지 않는 이유."""


def symbol_info(sym, save=True):
    """종목을 확인한다: 시세 캐시가 있으면 그것, 없으면 원천에서 받는다(save=True 면 캐시에 남긴다).
    시세를 받을 수 없는 번호·기호면 Refused — 잘못 친 번호로 한 달 동안 체결 안 되는 주문이 걸려 있지 않게."""
    c = px.load(HOME, sym)
    if c and c.get("bars"):
        return c
    try:
        if os.environ.get("PAPER_OFFLINE"):              # 시험: 원천에 묻지 않는다 (캐시에 없는 종목 = 받을 수 없는 종목)
            raise OSError("offline")
        if save:
            c = px.update(HOME, sym, now())
        elif px.market_of(sym) == "KR":
            bars, name = px.fetch_daum(sym, now())
            c = {"symbol": sym, "market": "KR", "name": name, "bars": bars}
        else:
            bars, name, _ = px.fetch_yahoo(sym, "US", now())
            c = {"symbol": sym, "market": "US", "name": name, "bars": bars}
    except Exception:
        c = None
    if not c or not c.get("bars"):
        raise Refused(f"{sym} 의 시세를 받을 수 없습니다 — 종목 번호·기호를 확인해 주세요 (한국은 여섯 자리 번호, 미국은 기호). "
                      "번호가 맞다면 시세 원천이 잠시 막힌 것이니 다시 내 주세요")
    return c


def tick_of(sym, live=False):
    """호가 단위. 미국 0.01, 한국은 가장 최근 1분 시세에 찍힌 값에서 읽는다 (없으면 None, live=True 면 원천에서 받아 본다)."""
    if px.market_of(sym) != "KR":
        return 0.01
    md = px.minute_dates(HOME, sym)
    if md:
        return mt.infer_tick("KR", px.load_minutes(HOME, sym, md[-1])["bars"])
    if live:
        try:
            days, _ = px._naver_minutes(sym, now())
            if days:
                return mt.infer_tick("KR", days[max(days)])
        except Exception:
            pass
    return None


def quote(sym, cache=None, live=False, krw=None, usd=None):
    """거래소가 가진 그 종목의 값 (주문 전에 묻기 — 장부에 아무것도 쓰지 않는다).
    반환: symbol·name·market·currency·close(마지막 정규장 종가)·close_date·last(가장 최근 1분 값 {price, at, session, session_label})·
    tick(호가 단위)·limit_up·limit_down(한국, 다음 정규장 기준 ±30%)·fx(미국이면 달러/원)·shares_for(금액을 주면 몇 주가 되는지)."""
    c = cache if cache is not None else (symbol_info(sym, save=False) if live else px.load(HOME, sym))
    if not c or not c.get("bars"):
        return None
    mkt = px.market_of(sym)
    bar = c["bars"][-1]
    lt = px.last_trade(HOME, sym)
    if lt:
        lt = {"price": lt["price"], "at": datetime.fromtimestamp(lt["ts"], KST).isoformat(timespec="minutes"),
              "session": lt["session"], "session_label": mk.LABEL.get(lt["session"], lt["session"])}
    out = {"symbol": sym, "name": c.get("name") or sym, "market": mkt, "currency": "USD" if mkt == "US" else "KRW",
           "close": bar["c"], "close_date": bar["d"], "last": lt, "tick": tick_of(sym, live=live)}
    if mkt == "KR":
        tick = out["tick"] or 1
        out["limit_up"] = math.floor(bar["c"] * 1.3 / tick) * tick
        out["limit_down"] = math.ceil(bar["c"] * 0.7 / tick) * tick
    rate = None
    if mkt == "US":
        f = px.load(HOME, px.FX_KEY)
        rate = f["bars"][-1]["c"] if f and f.get("bars") else None
        out["fx"] = rate
    ref = (lt or {}).get("price") or bar["c"]
    if krw or usd:
        cfg = config()
        load = 1 + buy_load(cfg, mkt)
        if mkt == "US":
            money = usd if usd else (krw / (rate * (1 + fx_spread(cfg))) if rate else None)
        else:
            money = krw
        out["shares_for"] = {"krw": krw, "usd": usd, "price": ref,
                             "qty": int(money // (ref * load)) if money else None,
                             "note": "가장 최근 값과 매수 수수료(미국은 환전 비용도)로 어림한 것 — 실제 체결가는 주문 뒤 첫 1분 시세"}
    return out


def place_order(p, dry=False):
    """주문 하나를 검사해 장부에 접수한다. p: symbol, side, type, qty, krw, price, session, valid_days, ref, client_id, requested_at.
    받지 않으면 Refused(이유). dry=True 면 검사만 하고 장부에 쓰지 않는다 — 접수될 내용(dict)을 돌려준다."""
    cfg = config()
    st = replay(read_ledger())
    if st["opened"] is None:
        raise Refused("계좌가 없습니다")
    sym = str(p.get("symbol", "")).upper()
    if sym in ("USD", px.FX_KEY):
        return place_fx_order(p, st, cfg, dry=dry)
    side, typ, price = p.get("side"), p.get("type") or "market", p.get("price")
    session = p.get("session") or "regular"
    qty, krw_amt = p.get("qty"), p.get("krw")
    if not sym or side not in ("buy", "sell") or typ not in ("market", "moc", "limit", "stop") or session not in ("regular", "all"):
        raise Refused("주문 내용이 올바르지 않습니다")
    mkt = px.market_of(sym)
    if mkt not in cfg["markets"]:
        raise Refused(f"{mkt} 시장은 허용되지 않습니다.")
    if typ in ("limit", "stop") and price is None:
        raise Refused("지정가·손절 주문에는 가격이 필요합니다.")
    if price is not None:
        price = float(price)
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", sym):
        raise Refused("종목 기호가 올바르지 않습니다")
    if side == "sell" and held(st, sym) == 0 and not any(o["status"] in OPEN and o["symbol"] == sym and o["side"] == "buy"
                                                          for o in st["orders"].values()):
        raise Refused(f"{sym} 을(를) 보유하고 있지 않습니다. 공매도는 없습니다.")
    info = symbol_info(sym, save=not dry)
    if price is not None and mkt == "KR":
        daily = info
        tick = tick_of(sym, live=dry)            # 호가 단위: 최근 시세에 실제로 찍힌 값들로 판단
        if tick and price % tick:
            raise Refused(f"호가 단위에 맞지 않습니다 — {sym} 은(는) {tick:,}원 단위입니다.")
        if daily and daily["bars"]:              # 상·하한가 (전일 종가의 ±30%)
            prev = daily["bars"][-1]["c"]
            if not prev * 0.7 <= price <= prev * 1.3:
                raise Refused(f"가격이 상·하한가 범위를 벗어납니다 — 직전 종가 {prev:,.0f}원의 ±30% 안이어야 합니다.")
    if session == "all" and typ != "limit":
        raise Refused("장전·장후(시간외)에는 지정가 주문만 낼 수 있습니다. 시장가·손절·종가 주문은 정규장에서만 체결됩니다.")
    data = {"ref": str(p.get("ref") or "")[:80], "symbol": sym, "name": info.get("name") or sym, "market": mkt,
            "side": side, "type": typ, "price": price, "session": session}
    if p.get("client_id"):
        data["client_id"] = p["client_id"]
        data["requested_at"] = p.get("requested_at")
    if side == "buy":
        if bool(qty) == bool(krw_amt):
            raise Refused("살 때는 주 수 또는 금액 중 하나만 적습니다.")
        if qty:
            data["qty"] = int(qty)
        else:
            data["krw"] = float(krw_amt)
        # 주문 가능 금액 확인 (실제 증권사처럼 접수 단계에서) — 수량 주문은 지정가나 직전 종가로 어림
        need = data.get("krw")
        if need is None:
            daily = info
            ref = price if typ == "limit" else (daily["bars"][-1]["c"] if daily and daily["bars"] else None)
            if ref is not None:
                rate = 1.0
                if mkt == "US":
                    fxd = px.load(HOME, px.FX_KEY)
                    rate = fxd["bars"][-1]["c"] if fxd and fxd["bars"] else None
                need = data["qty"] * ref * rate if rate else None
        have, what = st["cash"], f"원화 예수금 {round(st['cash']):,}원"
        if mkt == "US":                                  # 달러 예수금을 먼저 쓰고, 모자라면 원화를 환전해 산다(자동 환전일 때)
            fxd = px.load(HOME, px.FX_KEY)
            r = fxd["bars"][-1]["c"] if fxd and fxd["bars"] else 0
            auto = cfg.get("usd_shortfall", "auto") == "auto"
            have = st["usd"] * r + (st["cash"] if auto else 0)
            what = (f"원화 {round(st['cash']):,}원 + 달러 {st['usd']:,.2f}" if auto else f"달러 예수금 {st['usd']:,.2f}달러")
        if need is not None and need > have:
            raise Refused(f"주문 가능 금액이 모자랍니다 — 필요 약 {round(need):,}원, {what}")
    else:
        if krw_amt:
            raise Refused("팔 때는 주 수 또는 전량(all)으로 적습니다.")
        pending_buy = any(o["status"] in OPEN and o["symbol"] == sym and o["side"] == "buy"
                          for o in st["orders"].values())
        if held(st, sym) == 0 and not pending_buy:
            raise Refused(f"{sym} 을(를) 보유하고 있지 않습니다. 공매도는 없습니다.")
        data["qty"] = "all" if qty in (None, "all") else int(qty)
    days = int(p.get("valid_days") or cfg["order_valid_days"])
    data["valid_until"] = (now().date() + timedelta(days=days)).isoformat()
    data["id"] = f"O{len(st['orders']) + 1:04d}"
    if dry:
        return data
    append("order", data)
    return data["id"]


def place_fx_order(p, st, cfg, dry=False):
    """환전 주문 접수. 사기 = 원화를 달러로(원화 금액 krw 또는 달러 금액 usd), 팔기 = 달러를 원화로(usd 금액 또는 all)."""
    side, usd, krw_amt = p.get("side"), p.get("usd"), p.get("krw")
    if side not in ("buy", "sell") or (p.get("type") or "market") != "market" or p.get("price") is not None \
            or (p.get("session") or "regular") != "regular" or p.get("qty"):
        raise Refused("환전 주문은 사기·팔기와 금액만 적습니다 (값을 정해 두는 환전은 없습니다).")
    try:
        usd = None if usd in (None, "", "all") else round(float(usd), 2)
        krw_amt = float(krw_amt) if krw_amt else None
    except (TypeError, ValueError):
        raise Refused("환전 금액을 읽을 수 없습니다")
    data = {"ref": str(p.get("ref") or "")[:80], "symbol": px.FX_KEY, "market": "FX", "side": side, "type": "market",
            "price": None, "session": "regular"}
    if p.get("client_id"):
        data["client_id"] = p["client_id"]
        data["requested_at"] = p.get("requested_at")
    fxd = px.load(HOME, px.FX_KEY)
    rate = fxd["bars"][-1]["c"] if fxd and fxd["bars"] else None
    if side == "buy":
        if (usd is None) == (krw_amt is None) or (usd or krw_amt) <= 0:
            raise Refused("달러를 살 때는 원화 금액 또는 달러 금액 중 하나만 적습니다.")
        need = krw_amt if krw_amt else (usd * rate * (1 + fx_spread(cfg)) if rate else None)
        if need is not None and need > st["cash"]:
            raise Refused(f"주문 가능 금액이 모자랍니다 — 필요 약 {round(need):,}원, 원화 예수금 {round(st['cash']):,}원")
        data["krw" if krw_amt else "usd"] = krw_amt or usd
    else:
        if krw_amt or (usd is not None and usd <= 0):
            raise Refused("달러를 팔 때는 달러 금액 또는 전부(all)로 적습니다.")
        if st["usd"] < 0.01 or (usd or 0) > st["usd"] + 0.005:
            raise Refused(f"달러 예수금이 모자랍니다 — 보유 {st['usd']:,.2f}달러")
        data["usd"] = "all" if usd is None else usd
    days = int(p.get("valid_days") or cfg["order_valid_days"])
    data["valid_until"] = (now().date() + timedelta(days=days)).isoformat()
    data["id"] = f"O{len(st['orders']) + 1:04d}"
    if dry:
        return data
    append("order", data)
    return data["id"]


WATCH_WHEN = {"close_below": "정규장 종가가 {v} 아래", "close_above": "정규장 종가가 {v} 위",
              "price_below": "정규장 1분 값이 {v} 아래로", "price_above": "정규장 1분 값이 {v} 위로"}
WATCH_MAX = 50


def place_watch(p, dry=False):
    """값 조건 지켜보기 등록. p: symbol, when(close_below·close_above·price_below·price_above), value, ref, valid_days.
    주문을 내지 않는다 — 정기 실행이 확인해 state.json 의 watch_hits 에 올린다."""
    st = replay(read_ledger())
    if st["opened"] is None:
        raise Refused("계좌가 없습니다")
    sym = str(p.get("symbol", "")).upper()
    when = p.get("when")
    if when not in WATCH_WHEN:
        raise Refused("지켜볼 조건은 close_below·close_above·price_below·price_above 중 하나입니다")
    try:
        value = float(p.get("value"))
    except (TypeError, ValueError):
        raise Refused("지켜볼 값(value)이 숫자가 아닙니다")
    if not math.isfinite(value) or value <= 0:
        raise Refused("지켜볼 값(value)이 올바르지 않습니다")
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", sym) or sym in ("USD", px.FX_KEY):
        raise Refused("종목 기호가 올바르지 않습니다 (환율은 지켜볼 수 없습니다)")
    if px.market_of(sym) not in config()["markets"]:
        raise Refused(f"{px.market_of(sym)} 시장은 허용되지 않습니다.")
    if sum(w["status"] == "watching" for w in st["watches"].values()) >= WATCH_MAX:
        raise Refused(f"지켜보는 조건은 {WATCH_MAX}개까지입니다 — 필요 없는 것을 먼저 거둬 주세요")
    info = symbol_info(sym, save=not dry)
    days = int(p.get("valid_days") or 90)
    data = {"id": f"W{len(st['watches']) + 1:04d}", "ref": str(p.get("ref") or "")[:80], "symbol": sym,
            "name": info.get("name") or sym, "market": px.market_of(sym), "when": when, "value": value,
            "valid_until": (now().date() + timedelta(days=days)).isoformat()}
    if p.get("client_id"):
        data["client_id"] = p["client_id"]
        data["requested_at"] = p.get("requested_at")
    if dry:
        return data
    append("watch", data)
    return data["id"]


def watch_result(w, today):
    """지켜보는 조건이 닿았는지 시세 캐시로 확인한다 (등록 뒤의 시세만). 반환 (상태, 닿은 때 dict 또는 None).
    닿은 것은 다시 계산해도 같은 첫 순간이 나온다 (1분 시세 파일이 저장소에 쌓이므로)."""
    if w["status"] != "watching":
        return w["status"], None
    t0 = datetime.fromisoformat(w["ts"]).timestamp()
    below = w["when"].endswith("_below")
    hit = (lambda x: x < w["value"]) if below else (lambda x: x > w["value"])
    if w["when"].startswith("close_"):
        c = px.load(HOME, w["symbol"])
        for b in (c or {}).get("bars", []):
            ss = mk.sessions(w["market"], datetime.strptime(b["d"], "%Y-%m-%d").date())
            close = next((e for n, s_, e in ss if n == "r"), None)
            if close and close.timestamp() > t0 and hit(b["c"]):
                return "hit", {"at": close.isoformat(timespec="minutes"), "price": b["c"], "date": b["d"]}
    else:
        start = datetime.fromtimestamp(t0, KST).date() - timedelta(days=1)
        for d in px.minute_dates(HOME, w["symbol"]):
            if d < start.isoformat():
                continue
            for bar in px.load_minutes(HOME, w["symbol"], d)["bars"]:
                ses = bar[6] if len(bar) > 6 else "r"
                if bar[0] < t0 or ses != "r":
                    continue
                x = bar[3] if below else bar[2]
                if hit(x):
                    return "hit", {"at": datetime.fromtimestamp(bar[0], KST).isoformat(timespec="minutes"), "price": x, "date": d}
    if w["valid_until"] < today:
        return "expired", None
    return "watching", None


def check_request(req):
    """요청 하나(창구 파일과 같은 모양)를 거래소 규칙으로 검사만 한다 — 장부에 아무것도 쓰지 않는다.
    반환 {"ok": True, "action", "would": 접수될 내용, "earliest_fill"} 또는 {"ok": False, "why"}."""
    act = req.get("action", "order")
    try:
        st = replay(read_ledger())
        if req.get("client_id") and req["client_id"] in st["seen"]:
            raise Refused("이미 처리한 요청입니다 (같은 client_id)")
        if act == "cancel":
            o = st["orders"].get(req.get("order"))
            if not o or o["status"] not in OPEN:
                raise Refused(f"취소할 수 없는 주문입니다 ({req.get('order')})")
            return {"ok": True, "action": act, "would": {"order": o["id"], "status_now": o["status"]}}
        if act == "unwatch":
            w = st["watches"].get(req.get("watch"))
            if not w or w["status"] != "watching":
                raise Refused(f"거둘 수 없는 지켜보기입니다 ({req.get('watch')})")
            return {"ok": True, "action": act, "would": {"watch": w["id"]}}
        if act == "watch":
            return {"ok": True, "action": act, "would": place_watch(req, dry=True)}
        if act != "order":
            raise Refused("모르는 요청입니다 (order·cancel·watch·unwatch)")
        try:
            data = place_order(req, dry=True)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise Refused("주문 내용이 올바르지 않습니다")
        ef = mk.earliest_fill(data, now())
        return {"ok": True, "action": act, "would": data, "earliest_fill": ef.isoformat(timespec="minutes") if ef else None}
    except Refused as e:
        return {"ok": False, "action": act, "why": str(e)}


def cmd_check(a):
    """보내지 않고 검사만: --json '{요청}' (창구 파일과 같은 모양) 또는 order 와 같은 칸.
    출력 JSON 한 줄. 끝나는 값 0 = 받을 수 있음, 3 = 받지 않음."""
    if a.json:
        try:
            req = json.loads(a.json)
            assert isinstance(req, dict)
        except Exception:
            print(json.dumps({"ok": False, "why": "요청을 JSON 으로 읽을 수 없습니다"}, ensure_ascii=False))
            sys.exit(3)
    else:
        req = {k: v for k, v in {"symbol": a.symbol, "side": a.side, "type": a.type, "qty": a.qty, "krw": a.krw, "usd": a.usd,
                                 "price": a.price, "session": a.session, "valid_days": a.valid_days, "ref": a.ref}.items()
               if v is not None}
    r = check_request(req)
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r["ok"] else 3)


def cmd_quote(a):
    """주문 전에 물어볼 값 (읽기만). 캐시에 없는 종목은 원천에서 받아 보되 저장하지 않는다.
    출력 JSON 한 줄. 끝나는 값 0 = 찾음, 3 = 시세를 받을 수 없는 종목."""
    sym = a.symbol.upper()
    try:
        has = px.load(HOME, sym)
        q = quote(sym, live=not (has and has.get("bars")), krw=a.krw, usd=a.usd)
    except Refused as e:
        print(json.dumps({"ok": False, "symbol": sym, "why": str(e)}, ensure_ascii=False))
        sys.exit(3)
    if not q:
        print(json.dumps({"ok": False, "symbol": sym, "why": "시세가 없습니다"}, ensure_ascii=False))
        sys.exit(3)
    print(json.dumps({"ok": True, **q}, ensure_ascii=False))


def cmd_order(a):
    try:
        print(place_order({"symbol": a.symbol, "side": a.side, "type": a.type, "qty": a.qty, "krw": a.krw, "usd": a.usd,
                           "price": a.price, "session": a.session, "valid_days": a.valid_days, "ref": a.ref}))
    except Refused as e:
        sys.exit(str(e))


def handle_request(req, cid):
    """요청 하나를 지금 계좌에 접수한다. 받은 것도 안 받은 것도 장부에 남긴다. 반환 (결과, 사람 말).
    결과: "ok" 접수 · "no" 받지 않음 · "dup" 이미 처리한 요청."""
    st = replay(read_ledger())
    if cid in st["seen"]:
        return "dup", "이미 처리한 요청입니다"
    try:
        if not req:
            raise Refused("요청 파일을 읽을 수 없습니다")
        req["client_id"] = cid
        if req.get("action", "order") == "cancel":
            o = st["orders"].get(req.get("order"))
            if not o or o["status"] not in OPEN:
                raise Refused(f"취소할 수 없는 주문입니다 ({req.get('order')})")
            append("cancel", {"order": o["id"], "why": str(req.get("why") or "운용자 요청")[:200], "client_id": cid})
            return "ok", f"주문 {o['id']} 취소를 접수했습니다"
        if req.get("action") == "watch":
            try:
                wid = place_watch(req)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                raise Refused("지켜보기 요청 내용이 올바르지 않습니다")
            return "ok", f"조건 지켜보기를 등록했습니다 — {wid}"
        if req.get("action") == "unwatch":
            w = st["watches"].get(req.get("watch"))
            if not w or w["status"] != "watching":
                raise Refused(f"거둘 수 없는 지켜보기입니다 ({req.get('watch')})")
            append("unwatch", {"watch": w["id"], "why": str(req.get("why") or "운용자 요청")[:200], "client_id": cid})
            return "ok", f"지켜보기 {w['id']} 를 거뒀습니다"
        if req.get("action", "order") != "order":
            raise Refused("모르는 요청입니다 (order·cancel·watch·unwatch)")
        try:
            oid = place_order(req)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise Refused("주문 내용이 올바르지 않습니다")
        return "ok", f"주문을 접수했습니다 — 주문 번호 {oid}"
    except Refused as e:
        append("refuse", {"client_id": cid, "why": str(e), "ref": str(req.get("ref", ""))[:80],
                          "symbol": str(req.get("symbol", "")).upper()[:12], "side": req.get("side") if req.get("side") in ("buy", "sell") else None,
                          "requested_at": req.get("requested_at")})
        return "no", f"받지 않았습니다 — {e}"


def cmd_ingest(a):
    """주문 창구: inbox/ 의 요청 파일을 이름 순서대로 접수한다. 받은 것도 안 받은 것도 장부에 남기고 파일은 치운다.
    inbox/*.json 은 주인 계좌, inbox/{계정}/*.json 은 그 참가자 계좌 (명단에 없는 폴더는 건드리지 않고 알리기만 한다).
    요청 파일(JSON): {"client_id": "...", "action": "order"|"cancel", ...주문 내용 또는 "order": "O0001", "why": "..."}"""
    inbox = HOME / "inbox"
    here = ACCT
    accts = {x["id"]: x for x in accounts()}
    boxes = [(next(x for x in accts.values() if x["main"]), inbox)]
    if inbox.exists():
        for d in sorted(x for x in inbox.iterdir() if x.is_dir()):
            if d.name.lower() in accts:
                boxes.append((accts[d.name.lower()], d))
            elif any(d.glob("*.json")):
                print(f"  명단에 없는 계좌의 창구라 받지 않습니다: {d.name}")
    n_ok = n_no = 0
    opened = False
    for acct, box in boxes:
        files = sorted(box.glob("*.json")) if box.exists() else []
        if files and not acct["main"] and not opened:
            open_missing()
            opened = True
        use(acct)
        for f in files:
            try:
                req = json.loads(f.read_text(encoding="utf-8"))
                cid = str(req.get("client_id") or f.stem)[:60]
                if not isinstance(req, dict):
                    raise ValueError
            except Exception:
                req, cid = {}, f.stem[:60]
            req.pop("account", None)
            res, msg = handle_request(req, cid)
            if res != "dup":                              # 이미 처리한 요청(같은 파일이 다시 올라왔다)은 조용히 치운다
                print(f"  [{acct['id']}] {cid} — {msg}")
                n_ok, n_no = n_ok + (res == "ok"), n_no + (res == "no")
            f.unlink()
    use(here)
    print(f"주문 창구: 접수 {n_ok}건, 받지 않음 {n_no}건")


MAX_PER_ISSUE = 10


def parse_issue(body):
    """주문 이슈 본문에서 요청을 꺼낸다. JSON 하나 또는 여러 개(목록). ``` 로 감싼 부분이 있으면 그 안만 본다."""
    body = (body or "")[:20000]
    m = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    obj = json.loads(m.group(1) if m else body)
    reqs = obj if isinstance(obj, list) else [obj]
    if not reqs or len(reqs) > MAX_PER_ISSUE or not all(isinstance(r, dict) for r in reqs):
        raise ValueError
    return reqs


def owner_login(cfg):
    """거래소 주인의 GitHub 계정: 설정에 적힌 것 → 주인 계좌의 계정 → 저장소 주인."""
    return ((cfg.get("league") or {}).get("owner")
            or next((p.get("github") for p in cfg.get("players") or [] if p.get("main")), None)
            or os.environ.get("GITHUB_REPOSITORY_OWNER") or "")


def _save_config(cfg):
    """관리 명령으로 바뀐 명단·대회를 자료 폴더의 players.json 에 쓴다 (규칙·요율이 든 config.json 은 건드리지 않는다)."""
    (HOME / "players.json").write_text(json.dumps({k: cfg.get(k) for k in PRIVATE_KEYS if k in cfg}, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")


def _day(v):
    return datetime.strptime(str(v), "%Y-%m-%d").strftime("%Y-%m-%d")


def admin_do(cfg, req):
    """관리 명령 하나를 설정에 적용한다. 반환: 사람 말. 안 되면 Refused."""
    act = req.get("action")
    players = cfg.setdefault("players", [])
    league = cfg.setdefault("league", {})
    if act in ("add_player", "remove_player"):
        gh = str(req.get("github") or "").strip().lstrip("@")
        pid = str(req.get("id") or gh).strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,38}", pid) or (gh and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", gh)):
            raise Refused("계정 이름이 올바르지 않습니다 (영문·숫자·줄표)")
        key = lambda p: str(p.get("id") or p.get("github") or "").lower()
        cur = next((p for p in players if key(p) == pid), None)
        if act == "add_player":
            name = str(req.get("name") or (cur or {}).get("name") or gh or pid).strip()[:40]
            agent = str(req.get("agent") or "").strip()[:60] or None
            email = str(req.get("email") or "").strip().lower()[:120] or None
            if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise Refused("이메일이 올바르지 않습니다")
            if email and any(str(p.get("email") or "").lower() == email and p is not cur for p in players):
                raise Refused("그 이메일은 이미 다른 계좌에 쓰이고 있습니다")
            login = str(req.get("login") or "").strip().lower()[:60] or None      # 로그인하는 곳(sharktalk)에서의 아이디
            if login and any(str(p.get("login") or "").lower() == login and p is not cur for p in players):
                raise Refused("그 로그인 아이디는 이미 다른 계좌에 쓰이고 있습니다")
            if cur:                                       # 이미 있으면 이름·에이전트·이메일·아이디만 고친다
                cur["name"] = name
                for k, v in (("agent", agent), ("email", email), ("login", login), ("github", gh or None)):
                    if v:
                        cur[k] = v
                return f"`{pid}` 의 정보를 고쳤습니다 (이름 '{name}')"
            new = {"id": pid, "github": gh or None, "email": email, "login": login, "name": name, "agent": agent}
            if gh and gh.lower() == pid:
                new.pop("id")
            players.append({k: v for k, v in new.items() if v})
            return f"`{pid}` 을(를) '{name}'(으)로 명단에 넣었습니다. 계좌가 시작 금액 {cfg['initial_cash']:,}원으로 열립니다"
        if not cur:
            raise Refused(f"`{pid}` 은(는) 명단에 없습니다")
        if cur.get("main"):
            raise Refused("주인 계좌는 뺄 수 없습니다")
        players.remove(cur)
        return f"`{pid}` 을(를) 명단에서 뺐습니다. 장부는 그대로 남고, 더 이상 주문을 받지 않으며 전체 수익률 표에서 빠집니다"
    if act in ("add_contest", "remove_contest"):
        name = str(req.get("name") or "").strip()[:40]
        if not name:
            raise Refused("대회 이름이 필요합니다")
        cs = league.setdefault("contests", [])
        cur = next((c for c in cs if c.get("name") == name), None)
        if act == "remove_contest":
            if not cur:
                raise Refused(f"'{name}' 대회가 없습니다")
            cs.remove(cur)
            return f"'{name}' 대회를 뺐습니다"
        try:
            start = _day(req.get("start"))
            end = _day(req["end"]) if req.get("end") else None
        except Exception:
            raise Refused("날짜는 2026-12-01 처럼 적습니다")
        if end and end < start:
            raise Refused("끝 날이 시작 날보다 앞섭니다")
        new = {"name": name, "start": start, "end": end}
        if cur:
            cur.update(new)
        else:
            cs.append(new)
        return f"'{name}' 대회를 {start} ~ {end or '끝 없음'} 으로 정했습니다"
    raise Refused("모르는 관리 명령입니다 (add_player · remove_player · add_contest · remove_contest)")


def cmd_admin_issue(author, body):
    """관리 이슈: 주인 계정이 연 것만 받는다. 설정(config.json)을 고치고, 새 참가자의 계좌를 바로 연다."""
    cfg = config()
    owner = owner_login(cfg)
    if not owner or author.lower() != owner.lower():
        return [f"관리 명령은 거래소 주인만 낼 수 있습니다. `{author}` 계정의 요청은 받지 않았습니다."]
    try:
        reqs = parse_issue(body)
    except Exception:
        return ["관리 명령을 읽을 수 없습니다. 예: `{\"action\": \"add_player\", \"github\": \"계정\", \"name\": \"화면에 나올 이름\"}`"]
    lines, changed = [], False
    for req in reqs:
        try:
            lines.append(f"- {admin_do(cfg, req)}")
            changed = True
        except Refused as e:
            lines.append(f"- 하지 않았습니다 — {e}")
    if changed:
        _save_config(cfg)
        open_missing()
    roster = ", ".join(f"{x['name']}(`{x['id']}`)" for x in accounts())
    return lines + ["", f"지금 명단: {roster}"]


ADMIN_LOG = HOME / "docs" / "data" / "admin_log.json"


def cmd_admin_inbox(a):
    """관리 창구: 자료 폴더의 admin/*.json 을 이름 순서대로 처리한다 (sharktalk 관리자 화면이 올린다 — 관리자 확인은 거기서 끝났다).
    결과는 docs/data/admin_log.json(관리자 화면에 나온다)에 남기고 파일은 치운다."""
    box = HOME / "admin"
    files = sorted(box.glob("*.json")) if box.exists() else []
    if not files:
        return
    cfg = config()
    log = json.loads(ADMIN_LOG.read_text(encoding="utf-8")) if ADMIN_LOG.exists() else []
    changed = False
    for f in files:
        try:
            req = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(req, dict):
                raise ValueError
        except Exception:
            req = None
        try:
            if req is None:
                raise Refused("요청 파일을 읽을 수 없습니다")
            msg, ok = admin_do(cfg, req), True
            changed = True
        except Refused as e:
            msg, ok = f"하지 않았습니다 — {e}", False
        log.append({"at": now().isoformat(timespec="seconds"), "action": (req or {}).get("action"), "ok": ok,
                    "text": msg.replace("`", ""), "requested_at": (req or {}).get("requested_at")})
        f.unlink()
    if changed:
        _save_config(cfg)
        open_missing()
    ADMIN_LOG.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_LOG.write_text(json.dumps(log[-50:], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"관리 창구: {len(files)}건")


def cmd_issue(a):
    """이슈 하나를 처리한다. 제목이 "[관리]" 로 시작하면 관리 명령(주인만), 아니면 주문.
    주문 이슈 하나를 접수한다. 이슈를 쓴 GitHub 계정이 곧 계좌다 — 요청 안에 적힌 계좌는 보지 않는다.
    환경변수: PAPER_ISSUE_AUTHOR, PAPER_ISSUE_NUMBER, PAPER_ISSUE_BODY, PAPER_ISSUE_AT(이슈를 연 시각), PAPER_REPLY(답글을 적을 파일)."""
    author = os.environ.get("PAPER_ISSUE_AUTHOR", "").strip()
    num = re.sub(r"\D", "", os.environ.get("PAPER_ISSUE_NUMBER", "")) or "0"
    if os.environ.get("PAPER_ISSUE_TITLE", "").strip().startswith("[관리]"):
        text = "\n".join(cmd_admin_issue(author, os.environ.get("PAPER_ISSUE_BODY", "")))
        print(text)
        if os.environ.get("PAPER_REPLY"):
            Path(os.environ["PAPER_REPLY"]).write_text(text + "\n", encoding="utf-8")
        return
    acct = next((x for x in accounts() if x["github"] and x["github"].lower() == author.lower()), None)
    lines = []
    if not acct:
        lines.append(f"`{author}` 계정은 참가자 명단에 없어 주문을 받지 않았습니다. 거래소 주인에게 초대를 요청해 주세요.")
    else:
        open_missing()
        use(acct)
        try:
            reqs = parse_issue(os.environ.get("PAPER_ISSUE_BODY", ""))
        except Exception:
            reqs = None
        if reqs is None:
            res, msg = handle_request({}, f"issue-{num}")
            lines.append(f"- 받지 않았습니다 — 주문 내용을 읽을 수 없습니다. 주문 하나 또는 {MAX_PER_ISSUE}개까지의 목록을 정해진 모양으로 적어 주세요.")
        else:
            for i, req in enumerate(reqs):
                cid = str(req.get("client_id") or (f"issue-{num}" + (f"-{i + 1}" if len(reqs) > 1 else "")))[:60]
                req.pop("account", None)
                req.setdefault("requested_at", os.environ.get("PAPER_ISSUE_AT") or None)
                res, msg = handle_request(req, cid)
                lines.append(f"- {msg}")
        lines.insert(0, f"**{acct['name']}** 계좌 · 접수 시각 {now().strftime('%Y-%m-%d %H:%M')} (한국)")
        lines.append("")
        lines.append("체결은 주문 뒤에 시작한 1분 시세부터 이뤄지고, 매시 정기 실행 때 장부와 화면에 반영됩니다.")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("PAPER_REPLY"):
        Path(os.environ["PAPER_REPLY"]).write_text(text + "\n", encoding="utf-8")


def cmd_cancel(a):
    st = replay(read_ledger())
    o = st["orders"].get(a.order)
    if not o or o["status"] not in OPEN:
        sys.exit("기다리는 중이거나 일부만 체결된 주문만 취소할 수 있습니다.")
    append("cancel", {"order": a.order, "why": a.why})
    print("취소:", a.order)


def each_account(a):
    """--account 가 있으면 그 계좌만, 없으면 모든 계좌를 차례로."""
    accts = [pick(a.account)] if getattr(a, "account", None) else accounts()
    for acct in accts:
        use(acct)
        if read_ledger():
            yield acct


def cmd_update(a):
    cfg, t = config(), now()
    keys, need = set(), set()
    for _ in each_account(a):                             # 시세는 모든 계좌가 함께 쓴다
        st = replay(read_ledger())
        keys |= set(needed_keys(st, cfg))
        # 1분 시세: 살아 있는 주문·보유 종목만 (체결 계산에 쓰인다). 미국 종목이나 달러가 있으면 환율도.
        mine = {o["symbol"] for o in st["orders"].values() if o["status"] in OPEN} | {s for s, l in st["lots"].items() if l}
        mine |= {w["symbol"] for w in st["watches"].values() if w["status"] == "watching" and w["when"].startswith("price_")}
        if any(px.market_of(k) == "US" for k in mine) or st["usd"] >= 0.01:
            mine.add(px.FX_KEY)
        need |= mine
    for k in sorted(keys):
        try:
            c = px.update(HOME, k, t)
            print(f"  {k:8s} ~{c['bars'][-1]['d'] if c['bars'] else '없음'}  {c['name']}")
        except Exception as e:
            print(f"  {k:8s} 수집 실패: {e}")
    for k in sorted(need):
        try:
            n1, n5 = px.update_minutes(HOME, k, t)
            print(f"  {k:8s} 1분 시세 {n1}일" + (f", 5분으로 메운 날 {n5}일" if n5 else ""))
        except Exception as e:
            print(f"  {k:8s} 1분 시세 수집 실패: {e}")


def cmd_settle(a):
    for acct in each_account(a):
        _settle_one(acct)


def _settle_one(acct):
    for e in settle():
        d = e["data"]
        print(f" [{acct['id']}]", end="")
        if e["type"] == "fill":
            print(f"  체결 {d['order']} {d['symbol']} {d['side']} {d['qty']}주 @ {d['price']} ({d['date']})")
        elif e["type"] == "fx":
            print(f"  환전 {d.get('order') or d.get('for')} {d['side']} {d['usd']:,.2f}달러 ↔ {d['krw']:,}원 (적용 환율 {d['rate']})")
        elif e["type"] == "dividend":
            print(f"  배당 {d['symbol']} {d['qty']}주 세금 뗀 뒤 {d['net']:,} {d['ccy']} (배당락일 {d['ex_date']})")
        elif e["type"] == "split":
            print(f"  분할·병합 {d['symbol']} {d['den']}→{d['num']} · {d['qty_before']}주 → {d['qty_after']}주 ({d['date']})")
        else:
            print(f"  {e['type']} {d['order']} — {d['why']}")


def cmd_build(a):
    for acct in each_account(a):
        s = build()["summary"]
        print(f"화면 자료 갱신 [{acct['id']}]: 총자산 {s['total']:,}원 ({s['pnl_pct']:+.2f}%), 현금 {s['cash_pct']}%")
    lg = build_league()
    print(f"순위표: {len(lg['players'])}계좌")


def cmd_daily(a):
    use(pick(None))
    need_open(replay(read_ledger()))
    cmd_admin_inbox(a)                                    # 관리 창구 (참가자 넣고 빼기·대회)
    open_missing()                                        # 명단에 새로 들어온 참가자의 계좌를 연다
    cmd_ingest(a)                                         # 주문 창구 (주인 inbox/, 참가자 inbox/{이름표}/)
    print("가격 갱신"); cmd_update(a)
    print("체결"); cmd_settle(a)
    cmd_build(a)


def cmd_status(a):
    st = replay(read_ledger())
    need_open(st)
    print(f"원화 예수금 {round(st['cash']):,}원 · 달러 예수금 {st['usd']:,.2f}달러")
    for sym, lots in st["lots"].items():
        q = sum(l["qty"] for l in lots)
        if q:
            print(f"  {sym} {q}주 (원가 {round(sum(l['cost_krw'] for l in lots)):,}원)")
    for o in st["orders"].values():
        if o["status"] in OPEN:
            print(f"  {'일부 체결' if o['status'] == 'partial' else '대기'} {o['id']} {o['symbol']} {o['side']} {o['type']} ~{o['valid_until']}")


def cmd_verify(a):
    bad = 0
    for acct in each_account(a):
        ok, n = verify()
        head = f"[{acct['id']}] " if len(accounts()) > 1 else ""
        print(f"{head}장부 {n}줄 — 이상 없음" if ok else f"{head}장부 {n}번째 줄에서 지문이 맞지 않습니다")
        bad += not ok
    sys.exit(1 if bad else 0)


def main():
    p = argparse.ArgumentParser(description="모의 증권 거래 시스템")
    p.add_argument("--account")                                            # 다룰 계좌(참가자 GitHub 계정). 없으면 주인 계좌
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("open").set_defaults(f=cmd_open)
    s = sub.add_parser("order")
    s.add_argument("--ref"); s.add_argument("--symbol", required=True)   # --ref: 운용자가 붙이는 꼬리표 (거래소는 읽지 않는다)
    s.add_argument("--side", required=True, choices=["buy", "sell"])
    s.add_argument("--type", default=None, choices=["market", "moc", "limit", "stop"])
    s.add_argument("--qty"); s.add_argument("--krw", type=float); s.add_argument("--price", type=float)
    s.add_argument("--usd")                                                # 환전 주문(--symbol USD)의 달러 금액 또는 all
    s.add_argument("--valid-days", type=int, dest="valid_days")
    s.add_argument("--session", default="regular", choices=["regular", "all"])   # all = 장전·장후에도 (지정가만)
    s.set_defaults(f=cmd_order)
    s = sub.add_parser("cancel"); s.add_argument("--order", required=True); s.add_argument("--why", required=True)
    s.set_defaults(f=cmd_cancel)
    s = sub.add_parser("check")                                            # 보내지 않고 검사만 (읽기 전용)
    s.add_argument("--json"); s.add_argument("--ref"); s.add_argument("--symbol")
    s.add_argument("--side", choices=["buy", "sell"]); s.add_argument("--type", choices=["market", "moc", "limit", "stop"])
    s.add_argument("--qty"); s.add_argument("--krw", type=float); s.add_argument("--price", type=float); s.add_argument("--usd")
    s.add_argument("--valid-days", type=int, dest="valid_days"); s.add_argument("--session", choices=["regular", "all"])
    s.set_defaults(f=cmd_check)
    s = sub.add_parser("quote")                                            # 주문 전에 물어볼 값 (읽기 전용)
    s.add_argument("--symbol", required=True); s.add_argument("--krw", type=float); s.add_argument("--usd", type=float)
    s.set_defaults(f=cmd_quote)
    sub.add_parser("ingest").set_defaults(f=cmd_ingest)
    sub.add_parser("issue").set_defaults(f=cmd_issue)
    sub.add_parser("admin-inbox").set_defaults(f=cmd_admin_inbox)
    for n, f in [("update", cmd_update), ("settle", cmd_settle), ("build", cmd_build),
                 ("daily", cmd_daily), ("status", cmd_status), ("verify", cmd_verify)]:
        sub.add_parser(n).set_defaults(f=f)
    a = p.parse_args()
    # 장부는 거래소 한 곳만 쓴다: 클라우드가 쓰기로 정해져 있으면 이 PC 에서는 읽기만 한다 (시험 폴더는 예외)
    writes = {"open", "order", "cancel", "ingest", "issue", "admin-inbox", "update", "settle", "build", "daily"}
    # 자료 저장소(paper-exchange-data)를 받아 둔 폴더에는 .ledger-lock 표지가 있다 — PAPER_HOME 으로 가리켜도 쓰지 못한다
    real = (HOME / ".ledger-lock").exists()
    if (a.cmd in writes and config().get("ledger_writer") == "cloud" and not os.environ.get("GITHUB_ACTIONS")
            and (real or not os.environ.get("PAPER_HOME"))):
        sys.exit("이 장부는 클라우드 거래소(GitHub 자동 실행)만 씁니다. 주문은 일지 도구로 요청하고, 상태는 git pull 로 받아 보세요.")
    use(pick(a.account))
    a.f(a)


if __name__ == "__main__":
    main()
