"""모의 증권 거래소 — 계좌·주문·체결·평가만 한다.

거래소는 "왜 샀는지"를 모른다. 결정 기록·보고서·교훈은 운용 일지(통합 개발/모의투자-일지)의 일이다.
주문에는 운용자가 붙인 꼬리표(--ref)만 실려 오고, 거래소는 그 내용을 읽지 않는다.

장부는 {HOME}/ledger/ledger.jsonl 한 파일이다. 줄 추가만 하고, 줄마다 앞줄의 지문(hash)을 품는다.
상태(현금·보유·주문 상태)는 장부를 처음부터 다시 읽어 만든다.

쓰는 법 (통합 개발/모의투자 에서):
  python broker/broker.py open                      계좌 개설 (장부가 비었을 때 한 번)
  python broker/broker.py order --symbol MU --side buy --krw 5000000 [--ref D001]        시장가(기본)
  python broker/broker.py order --symbol MU --side buy --qty 10 --type moc               그날 종가에
  python broker/broker.py order --symbol MU --side buy --qty 3 --type limit --price 775 --session all   시간외 포함 지정가
  python broker/broker.py order --symbol MU --side sell --qty all --type stop --price 700
  python broker/broker.py cancel --order O0001 --why ..
  python broker/broker.py daily                     시세 갱신 → 체결 → 화면 자료 만들기
  python broker/broker.py status | verify
  python broker/broker.py ingest                    주문 창구(inbox/)에 들어온 요청을 접수한다

장부는 거래소 한 곳만 쓴다 (config.json "ledger_writer": "cloud" 일 때 = GitHub 자동 실행).
  운용자는 주문 요청 파일을 inbox/ 에 올리기만 하고, 거래소가 받아서 자기 시각으로 접수한다.
  그래서 이 PC 에서 open·order·cancel·settle·daily·ingest·build 를 직접 돌리면 거절된다 (읽기 전용인 status·verify 는 된다).
시험할 때는 환경변수 PAPER_HOME(임시 폴더), PAPER_NOW(가짜 현재 시각)를 쓴다 — 그때는 잠금이 풀린다.
"""
import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prices as px  # noqa: E402
import matching as mt  # noqa: E402

KST = px.KST
HOME = Path(os.environ.get("PAPER_HOME") or Path(__file__).resolve().parent.parent)
LEDGER = HOME / "ledger" / "ledger.jsonl"
STATE_OUT = HOME / "docs" / "data" / "state.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def now():
    v = os.environ.get("PAPER_NOW")
    return datetime.fromisoformat(v).astimezone(KST) if v else datetime.now(KST)


def config():
    return json.loads((HOME / "config.json").read_text(encoding="utf-8"))


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


# ---------- 상태 다시 만들기 ----------
def replay(events):
    st = {"cash": 0.0, "opened": None, "initial": 0.0, "lots": {}, "orders": {}, "fills": [],
          "realized": {}, "last_buy": {}, "last_buy_ts": {}, "refused": [], "seen": set()}
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
            st["cash"] += d["cash_delta"]
            st["fills"].append({**d, "ts": e["ts"]})
            lots = st["lots"].setdefault(d["symbol"], [])
            if d["side"] == "buy":                      # 산 주문마다 한 묶음 — 팔 때 먼저 산 것부터 줄인다
                lots.append({"order": d["order"], "qty": d["qty"], "cost_krw": -d["cash_delta"],
                             "unit_local": d["price"], "date": d["date"]})
                st["last_buy"][d["symbol"]] = d["date"]
                st["last_buy_ts"][d["symbol"]] = d.get("last_ts")
            else:
                left, net = d["qty"], d["cash_delta"]
                per_share = net / d["qty"]
                while left > 0 and lots:
                    lot = lots[0]
                    take = min(left, lot["qty"])
                    cost = lot["cost_krw"] * take / lot["qty"]
                    st["realized"][lot["order"]] = st["realized"].get(lot["order"], 0.0) + per_share * take - cost
                    lot["qty"] -= take
                    lot["cost_krw"] -= cost
                    left -= take
                    if lot["qty"] == 0:
                        lots.pop(0)
        # 그 밖의 줄(옛 장부의 결정·보고 등)은 거래소가 읽지 않는다
    return st


def held(st, sym):
    return sum(l["qty"] for l in st["lots"].get(sym, []))


# ---------- 체결 ----------
OPEN = ("pending", "partial")          # 아직 살아 있는 주문


def kst_iso(ts):
    return datetime.fromtimestamp(ts, KST).isoformat(timespec="minutes") if ts else None


def settle():
    """살아 있는 주문을 시간 순서대로 체결한다. 계산은 matching.py, 여기서는 돈·수량 확인과 장부 기록."""
    cfg = config()
    fee_rate = cfg["fee_rate"]
    today = now().date().isoformat()
    done = []
    while True:
        st = replay(read_ledger())
        live = [o for o in st["orders"].values() if o["status"] in OPEN]
        if not live:
            break
        fx_daily = px.load(HOME, px.FX_KEY)

        def rate_at(market, ts):
            if market != "US":
                return 1.0
            return px.fx_at(HOME, ts, fx_daily)[0]

        best = None
        for o in live:
            sym = o["symbol"]

            def size_fn(price, ts, o=o):
                r = rate_at(o["market"], ts)
                return math.floor(o["krw"] / (price * r * (1 + fee_rate))) if r else 0

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
        ts = f["last_ts"] or f["sort_ts"]
        rate = rate_at(o["market"], ts)
        if rate is None:
            break                                       # 환율이 아직 없다 — 다음 실행에서
        gross = f["qty"] * f["price"] * rate
        fee = gross * fee_rate
        if o["side"] == "buy":
            if gross + fee > st["cash"] + 0.5:
                done.append(append("reject", {"order": o["id"], "date": f["date"],
                                              "why": f"현금 부족 — 필요 {round(gross + fee):,}원, 보유 {round(st['cash']):,}원"}))
                continue
            delta = -(gross + fee)
        else:
            delta = gross - fee
        done.append(append("fill", {
            "order": o["id"], "ref": o.get("ref", ""), "symbol": o["symbol"], "market": o["market"],
            "side": o["side"], "date": f["date"], "price": f["price"], "fx": rate, "qty": f["qty"],
            "total": f["total"], "remaining": f["total"] - o["filled_qty"] - f["qty"],
            "at": kst_iso(f["last_ts"]), "first_at": kst_iso(f["first_ts"]), "last_ts": f["last_ts"],
            "precision": f["precision"], "pieces": f["pieces"], "triggered": f["triggered"],
            "session": f.get("session") or "r",
            "gross_krw": round(gross), "fee_krw": round(fee), "cash_delta": round(delta),
            "cash_after": round(st["cash"] + round(delta))}))
    return done


# ---------- 화면 자료 ----------
def needed_keys(st, cfg):
    keys = {b["symbol"] for b in cfg["benchmark"]} | {px.FX_KEY}
    keys |= {s for s, l in st["lots"].items() if l}
    keys |= {o["symbol"] for o in st["orders"].values()}
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
        c = caches.get(sym)
        return c["name"] if c else sym

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
    total = st["cash"] + invested
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
    for d in sorted(dates):
        cash, qty = st["initial"], {}
        for f in st["fills"]:
            if f["date"] <= d:
                cash += f["cash_delta"]
                qty[f["symbol"]] = qty.get(f["symbol"], 0) + (f["qty"] if f["side"] == "buy" else -f["qty"])
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
            order_pnl[o["id"]] = {"realized_krw": round(r), "unrealized_krw": round(u), "total_krw": round(r + u)}

    orders = [{**o, "name": name(o["symbol"])} for o in st["orders"].values()]

    # 흐름(최근 것부터)
    feed = []
    for e in reversed(events):
        t, d = e["type"], e["data"]
        if t == "open":
            txt = f"계좌를 열었습니다. 시작 금액 {int(d['initial_cash']):,}원."
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
            txt = (f"체결 {d['order']} — {name(d['symbol'])} {d['qty']}주 {'샀습니다' if d['side'] == 'buy' else '팔았습니다'}{part}. "
                   f"{when} 가격 {d['price']:,}, 금액 {d['gross_krw']:,}원, 비용 {d['fee_krw']:,}원.")
        elif t == "reject":
            txt = f"거부 {d['order']} — {d['why']}"
        elif t == "expire":
            txt = f"만료 {d['order']} — {d['why']}"
        elif t == "cancel":
            txt = f"취소 {d['order']} — {d['why']}"
        elif t == "refuse":
            txt = f"주문 요청을 받지 않았습니다 — {d['why']}"
        else:
            continue
        feed.append({"seq": e["seq"], "ts": e["ts"], "type": t, "text": txt})

    asof = {k: (caches[k]["bars"][-1]["d"] if caches.get(k) and caches[k]["bars"] else None) for k in keys}
    out = {
        "account": cfg["account_name"], "updated": now().isoformat(timespec="seconds"),
        "opened": opened, "initial": st["initial"], "fee_rate": cfg["fee_rate"],
        "rules": cfg["rules"],
        "benchmark": [{**b, "name": name(b["symbol"])} for b in cfg["benchmark"]],
        "summary": {
            "total": round(last["total"]), "cash": round(st["cash"]), "invested": round(invested),
            "cash_pct": round(st["cash"] / total * 100, 1) if total else 100,
            "ext_delta_krw": sum(p["ext"]["value_krw"] - p["value_krw"] for p in positions
                                 if p.get("ext") and p["ext"].get("value_krw") is not None),
            "pnl_krw": round(last["total"] - st["initial"]),
            "pnl_pct": round((last["total"] / st["initial"] - 1) * 100, 2) if st["initial"] else 0,
            "bench_pct": round((last["bench"] / st["initial"] - 1) * 100, 2) if last.get("bench") else None,
            "fees_krw": sum(f["fee_krw"] for f in st["fills"]),
            "n_orders": len(orders), "n_filled": sum(o["status"] == "filled" for o in orders),
            "n_pending": sum(o["status"] in OPEN for o in orders),
        },
        "positions": positions, "equity": equity,
        "orders": sorted(orders, key=lambda o: o["id"], reverse=True),
        "order_pnl": order_pnl,
        "refused": list(reversed(st["refused"])),
        "feed": feed[:300],
        "integrity": {"ok": ok, "lines": len(events), "head": events[-1]["hash"][:12] if events else None,
                      "broken_at": None if ok else n},
        "prices_asof": asof,
        "fx": px.close_on_or_before(fx, today)["c"] if fx and fx["bars"] else None,
    }
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ---------- 명령 ----------
def need_open(st):
    if st["opened"] is None:
        sys.exit("계좌가 없습니다. 먼저: python broker/broker.py open")


def cmd_open(a):
    if read_ledger():
        sys.exit("이미 열린 계좌입니다.")
    cfg = config()
    append("open", {"account": cfg["account_name"], "initial_cash": cfg["initial_cash"],
                    "opened": now().date().isoformat(), "fee_rate": cfg["fee_rate"], "rules": cfg["rules"]})
    print(f"계좌 개설: {cfg['account_name']} · {cfg['initial_cash']:,}원")


class Refused(Exception):
    """주문을 받지 않는 이유."""


def place_order(p):
    """주문 하나를 검사해 장부에 접수한다. p: symbol, side, type, qty, krw, price, session, valid_days, ref, client_id, requested_at.
    받지 않으면 Refused(이유)."""
    cfg = config()
    st = replay(read_ledger())
    if st["opened"] is None:
        raise Refused("계좌가 없습니다")
    sym = str(p.get("symbol", "")).upper()
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
    if price is not None and mkt == "KR":
        daily = px.load(HOME, sym)
        md = px.minute_dates(HOME, sym)
        if md:                                   # 호가 단위: 최근 시세에 실제로 찍힌 값들로 판단
            tick = mt.infer_tick("KR", px.load_minutes(HOME, sym, md[-1])["bars"])
            if price % tick:
                raise Refused(f"호가 단위에 맞지 않습니다 — {sym} 은(는) {tick:,}원 단위입니다.")
        if daily and daily["bars"]:              # 상·하한가 (전일 종가의 ±30%)
            prev = daily["bars"][-1]["c"]
            if not prev * 0.7 <= price <= prev * 1.3:
                raise Refused(f"가격이 상·하한가 범위를 벗어납니다 — 직전 종가 {prev:,.0f}원의 ±30% 안이어야 합니다.")
    if session == "all" and typ != "limit":
        raise Refused("장전·장후(시간외)에는 지정가 주문만 낼 수 있습니다. 시장가·손절·종가 주문은 정규장에서만 체결됩니다.")
    data = {"ref": p.get("ref") or "", "symbol": sym, "market": mkt, "side": side, "type": typ,
            "price": price, "session": session}
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
            daily = px.load(HOME, sym)
            ref = price if typ == "limit" else (daily["bars"][-1]["c"] if daily and daily["bars"] else None)
            if ref is not None:
                rate = 1.0
                if mkt == "US":
                    fxd = px.load(HOME, px.FX_KEY)
                    rate = fxd["bars"][-1]["c"] if fxd and fxd["bars"] else None
                need = data["qty"] * ref * rate if rate else None
        if need is not None and need > st["cash"]:
            raise Refused(f"주문 가능 금액이 모자랍니다 — 필요 약 {round(need):,}원, 현금 {round(st['cash']):,}원")
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
    append("order", data)
    return data["id"]


def cmd_order(a):
    try:
        print(place_order({"symbol": a.symbol, "side": a.side, "type": a.type, "qty": a.qty, "krw": a.krw,
                           "price": a.price, "session": a.session, "valid_days": a.valid_days, "ref": a.ref}))
    except Refused as e:
        sys.exit(str(e))


def cmd_ingest(a):
    """주문 창구: inbox/ 의 요청 파일을 이름 순서대로 접수한다. 받은 것도 안 받은 것도 장부에 남기고 파일은 치운다.
    요청 파일(JSON): {"client_id": "...", "action": "order"|"cancel", ...주문 내용 또는 "order": "O0001", "why": "..."}"""
    inbox = HOME / "inbox"
    files = sorted(f for f in inbox.glob("*.json")) if inbox.exists() else []
    n_ok = n_no = 0
    for f in files:
        try:
            req = json.loads(f.read_text(encoding="utf-8"))
            cid = str(req.get("client_id") or f.stem)
            req["client_id"] = cid
        except Exception:
            req, cid = {}, f.stem
        st = replay(read_ledger())
        if cid in st["seen"]:
            pass                                          # 이미 처리한 요청 (같은 파일이 다시 올라왔다)
        else:
            try:
                if not req:
                    raise Refused("요청 파일을 읽을 수 없습니다")
                if req.get("action", "order") == "cancel":
                    o = st["orders"].get(req.get("order"))
                    if not o or o["status"] not in OPEN:
                        raise Refused(f"취소할 수 없는 주문입니다 ({req.get('order')})")
                    append("cancel", {"order": o["id"], "why": req.get("why") or "운용자 요청", "client_id": cid})
                    print(f"  취소 접수 {o['id']}")
                else:
                    oid = place_order(req)
                    print(f"  주문 접수 {oid} ← {cid}")
                n_ok += 1
            except Refused as e:
                append("refuse", {"client_id": cid, "why": str(e), "ref": req.get("ref", ""),
                                  "symbol": str(req.get("symbol", "")).upper(), "side": req.get("side"),
                                  "requested_at": req.get("requested_at")})
                print(f"  받지 않음 {cid} — {e}")
                n_no += 1
        f.unlink()
    print(f"주문 창구: 접수 {n_ok}건, 받지 않음 {n_no}건")


def cmd_cancel(a):
    st = replay(read_ledger())
    o = st["orders"].get(a.order)
    if not o or o["status"] not in OPEN:
        sys.exit("기다리는 중이거나 일부만 체결된 주문만 취소할 수 있습니다.")
    append("cancel", {"order": a.order, "why": a.why})
    print("취소:", a.order)


def cmd_update(a):
    st = replay(read_ledger())
    t = now()
    for k in needed_keys(st, config()):
        try:
            c = px.update(HOME, k, t)
            print(f"  {k:8s} ~{c['bars'][-1]['d'] if c['bars'] else '없음'}  {c['name']}")
        except Exception as e:
            print(f"  {k:8s} 수집 실패: {e}")
    # 1분 시세: 살아 있는 주문·보유 종목만 (체결 계산에 쓰인다). 미국 종목이 있으면 환율도.
    need = {o["symbol"] for o in st["orders"].values() if o["status"] in OPEN} | {s for s, l in st["lots"].items() if l}
    if any(px.market_of(k) == "US" for k in need):
        need.add(px.FX_KEY)
    for k in sorted(need):
        try:
            n1, n5 = px.update_minutes(HOME, k, t)
            print(f"  {k:8s} 1분 시세 {n1}일" + (f", 5분으로 메운 날 {n5}일" if n5 else ""))
        except Exception as e:
            print(f"  {k:8s} 1분 시세 수집 실패: {e}")


def cmd_settle(a):
    for e in settle():
        d = e["data"]
        if e["type"] == "fill":
            print(f"  체결 {d['order']} {d['symbol']} {d['side']} {d['qty']}주 @ {d['price']} ({d['date']})")
        else:
            print(f"  {e['type']} {d['order']} — {d['why']}")


def cmd_build(a):
    s = build()["summary"]
    print(f"화면 자료 갱신: 총자산 {s['total']:,}원 ({s['pnl_pct']:+.2f}%), 현금 {s['cash_pct']}%")


def cmd_daily(a):
    need_open(replay(read_ledger()))
    cmd_ingest(a)
    print("가격 갱신"); cmd_update(a)
    print("체결"); cmd_settle(a)
    cmd_build(a)


def cmd_status(a):
    st = replay(read_ledger())
    need_open(st)
    print(f"현금 {round(st['cash']):,}원")
    for sym, lots in st["lots"].items():
        q = sum(l["qty"] for l in lots)
        if q:
            print(f"  {sym} {q}주 (원가 {round(sum(l['cost_krw'] for l in lots)):,}원)")
    for o in st["orders"].values():
        if o["status"] in OPEN:
            print(f"  {'일부 체결' if o['status'] == 'partial' else '대기'} {o['id']} {o['symbol']} {o['side']} {o['type']} ~{o['valid_until']}")


def cmd_verify(a):
    ok, n = verify()
    print(f"장부 {n}줄 — 이상 없음" if ok else f"장부 {n}번째 줄에서 지문이 맞지 않습니다")
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(description="모의 증권 거래 시스템")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("open").set_defaults(f=cmd_open)
    s = sub.add_parser("order")
    s.add_argument("--ref"); s.add_argument("--symbol", required=True)   # --ref: 운용자가 붙이는 꼬리표 (거래소는 읽지 않는다)
    s.add_argument("--side", required=True, choices=["buy", "sell"])
    s.add_argument("--type", default="market", choices=["market", "moc", "limit", "stop"])
    s.add_argument("--qty"); s.add_argument("--krw", type=float); s.add_argument("--price", type=float)
    s.add_argument("--valid-days", type=int, dest="valid_days")
    s.add_argument("--session", default="regular", choices=["regular", "all"])   # all = 장전·장후에도 (지정가만)
    s.set_defaults(f=cmd_order)
    s = sub.add_parser("cancel"); s.add_argument("--order", required=True); s.add_argument("--why", required=True)
    s.set_defaults(f=cmd_cancel)
    sub.add_parser("ingest").set_defaults(f=cmd_ingest)
    for n, f in [("update", cmd_update), ("settle", cmd_settle), ("build", cmd_build),
                 ("daily", cmd_daily), ("status", cmd_status), ("verify", cmd_verify)]:
        sub.add_parser(n).set_defaults(f=f)
    a = p.parse_args()
    # 장부는 거래소 한 곳만 쓴다: 클라우드가 쓰기로 정해져 있으면 이 PC 에서는 읽기만 한다 (시험 폴더는 예외)
    writes = {"open", "order", "cancel", "ingest", "update", "settle", "build", "daily"}
    if (a.cmd in writes and config().get("ledger_writer") == "cloud" and not os.environ.get("GITHUB_ACTIONS")
            and not os.environ.get("PAPER_HOME")):
        sys.exit("이 장부는 클라우드 거래소(GitHub 자동 실행)만 씁니다. 주문은 일지 도구로 요청하고, 상태는 git pull 로 받아 보세요.")
    a.f(a)


if __name__ == "__main__":
    main()
