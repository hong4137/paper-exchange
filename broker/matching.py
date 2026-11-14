"""체결 엔진 — 주문 하나가 다음에 어떻게 체결되는지 계산한다 (장부에는 쓰지 않는다).

정밀도 3단: 그날의 1분 시세 → (미국) 5분 시세 → 하루 시세.
  1분·5분: 주문 접수 뒤에 시작한 봉부터 본다.
    시장가  첫 봉의 시가에서 호가 차이만큼 불리하게.
    지정가  값이 지정가를 지나갔을 때만, 지정가(시가가 더 유리하면 시가)에.
    손절    값이 손절가에 닿으면 그때부터 시장가.
    한 봉에서 가져갈 수 있는 양은 그 봉 거래량의 일부(participation)뿐 — 남으면 다음 봉으로.
  하루: 1분·5분 시세를 놓친 날의 어림. 시장가는 그날 시가, 지정가·손절은 고가·저가로 판단.
종가 주문(moc)은 언제나 그날 공식 종가.
호가 단위: 한국은 그날 시세에서 읽는다(표를 외우지 않는다), 미국은 0.01.
시간대: 봉마다 정규장("r")·장전("pre")·장후("post") 표시가 있다.
  시장가·손절은 정규장에서만 체결된다. 지정가는 주문에 '시간외 포함'(session=all)을 적었을 때만 장전·장후에서도 체결된다.
  미국 장전·장후 봉에는 거래량이 없어, 그때는 1분에 살 수 있는 금액 한도(ext_max_krw_per_min)로 대신한다.
"""
import math
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
PRECISION = {60: "1분", 300: "5분"}


TICKS = (1000, 500, 250, 100, 50, 25, 10, 5, 1)


def infer_tick(market, bars):
    """한국 호가 단위를 그날 시세에서 읽는다. 대량매매 같은 이상 값이 드물게 섞이므로
    값의 97% 이상이 나누어떨어지는 가장 큰 단위를 고른다."""
    if market != "KR":
        return 0.01
    vals = [int(round(p)) for b in bars for p in b[1:5]]
    if not vals:
        return 1
    for t in TICKS:
        if sum(v % t == 0 for v in vals) >= 0.97 * len(vals):
            return t
    return 1


def _round_tick(p, tick, up):
    n = p / tick
    n = math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)
    return round(n * tick, 4)


def match_intraday(o, bars, start_ts, remaining, size_fn, cfg, triggered, ext_cap_fn=None):
    """한 거래일의 봉들로 체결을 계산. 반환 None(체결 없음) 또는 dict.
    remaining=None 이면 금액 주문 — 첫 체결가에서 size_fn(가격, 시각) 으로 수량을 정한다."""
    market = o["market"]
    tick = infer_tick(market, bars)
    part, share = cfg["participation"], cfg["slippage_range_share"]
    buy = o["side"] == "buy"
    typ = o["type"]
    got, cost, first, last, pieces, trig, ses0 = 0, 0.0, None, None, 0, triggered, None
    ext_ok = typ == "limit" and o.get("session") == "all"
    for b in bars:
        t, op, hi, lo, cl, vol = b[:6]
        ses = b[6] if len(b) > 6 else "r"
        if t < start_ts or (ses != "r" and not ext_ok):
            continue
        half = max(tick, share * (hi - lo))
        price = None
        if typ == "market" or (typ == "stop" and trig):
            price = min(hi, op + half) if buy else max(lo, op - half)
            price = _round_tick(price, tick, up=buy)
        elif typ == "limit":
            lim = o["price"]
            if buy and (op <= lim or lo < lim):
                price = min(op, lim)
            elif not buy and (op >= lim or hi > lim):
                price = max(op, lim)
        elif typ == "stop":
            stop = o["price"]
            if (not buy and lo <= stop) or (buy and hi >= stop):
                trig = True
                base = min(op, stop) if not buy else max(op, stop)
                price = max(lo, base - half) if not buy else min(hi, base + half)
                price = _round_tick(price, tick, up=buy)
        if price is None:
            continue
        if remaining is None:
            remaining = size_fn(price, t)
            if remaining < 1:
                return {"too_small": True, "price": price, "ts": t}
        cap = math.floor(vol * part)
        if ses != "r" and not vol and ext_cap_fn:        # 거래량 자료가 없는 시간외 봉
            cap = ext_cap_fn(price, t)
        take = min(remaining - got, cap)
        if take < 1:
            continue
        ses0 = ses0 or ses
        got += take
        cost += take * price
        pieces += 1
        first = t if first is None else first
        last = t
        if got >= remaining:
            break
    if not got:
        return None
    return {"qty": got, "total": remaining, "price": round(cost / got, 4), "first_ts": first, "last_ts": last,
            "pieces": pieces, "triggered": trig, "session": ses0}


def first_eligible(placed_ts, market):
    """(하루 시세로 어림할 때) 주문 뒤 처음 열리는 거래일의 가장 이른 날짜."""
    t = datetime.fromisoformat(placed_ts).astimezone(KST)
    d = t.date()
    same_day = t.hour < 9 if market == "KR" else t.hour < 22      # 미국장은 한국 밤에 열린다
    return (d if same_day else d + timedelta(days=1)).isoformat()


def _session_ts(d, market, close=False):
    """하루 시세로 체결할 때 순서를 매기기 위한 대략의 시각."""
    base = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=KST)
    if market == "KR":
        return (base + timedelta(hours=15, minutes=30 if close else 0) if close else base + timedelta(hours=9)).timestamp()
    return (base + timedelta(days=1, hours=6) if close else base + timedelta(hours=23, minutes=30)).timestamp()


def match_daily(o, bar):
    """하루 시세 한 줄로 어림. 반환: 가격 또는 None."""
    typ, buy = o["type"], o["side"] == "buy"
    if typ == "moc":
        return bar["c"]
    if typ == "market":
        return bar["o"]
    if typ == "limit":
        if buy and bar["l"] <= o["price"]:
            return min(bar["o"], o["price"])
        if not buy and bar["h"] >= o["price"]:
            return max(bar["o"], o["price"])
    if typ == "stop":
        if not buy and bar["l"] <= o["price"]:
            return min(bar["o"], o["price"])
        if buy and bar["h"] >= o["price"]:
            return max(bar["o"], o["price"])
    return None


def next_event(o, ctx):
    """주문 o 의 다음 사건.
    ctx: daily(일별 캐시), minutes(d)->{step,bars}|None, minute_dates[list], held(int), pending_buy(bool),
         last_buy_ts(float|None), last_buy_date(str|None), size_fn, cfg, today(str)
    반환: None | ("reject", 사유) | ("expire", 사유) | ("fill", {...})"""
    market = o["market"]
    daily = ctx["daily"]
    bars_by_date = {b["d"]: b for b in (daily["bars"] if daily else [])}
    placed = datetime.fromisoformat(o["ts"])
    start_ts = placed.timestamp()
    done_qty = o.get("filled_qty", 0)
    total = o.get("qty_total")
    if o["side"] == "sell":
        if ctx["held"] == 0:
            return None if ctx["pending_buy"] else ("reject", "보유하지 않은 종목")
        if total is None:
            total = ctx["held"] if o.get("qty") in (None, "all") else o["qty"]
            if total > ctx["held"]:
                return ("reject", f"보유 수량 부족 — 주문 {total}주, 보유 {ctx['held']}주")
        if o["type"] != "moc" and ctx["last_buy_ts"]:
            start_ts = max(start_ts, ctx["last_buy_ts"] + 1)        # 사기도 전에 손절이 나가지 않게
    elif total is None and o.get("qty"):
        total = o["qty"]
    remaining = None if total is None else total - done_qty
    # 일부만 체결된 주문은 마지막으로 체결된 1분 다음부터 이어 간다 (같은 1분을 두 번 쓰지 않는다)
    if o.get("last_fill_ts"):
        start_ts = max(start_ts, o["last_fill_ts"] + 1)
    after_date = o.get("last_fill_date") if o.get("last_fill_date") and not o.get("last_fill_ts") else None

    d_min = (placed.astimezone(KST).date() - timedelta(days=1)).isoformat()
    elig = first_eligible(o["ts"], market)
    if o["side"] == "sell" and o["type"] != "moc" and ctx["last_buy_date"]:
        nxt = (datetime.strptime(ctx["last_buy_date"], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        elig_daily = max(elig, nxt)
    else:
        elig_daily = elig
    dates = sorted(d for d in set(bars_by_date) | set(ctx["minute_dates"]) if d_min <= d <= o["valid_until"])

    for d in dates:
        if (o.get("last_fill_date") and d < o["last_fill_date"]) or (after_date and d <= after_date):
            continue
        closed = d in bars_by_date
        if o["type"] == "moc":
            if closed and d >= elig:
                return _daily_fill(o, d, bars_by_date[d]["c"], remaining, ctx, _session_ts(d, market, close=True))
            continue
        m = ctx["minutes"](d)
        if m and m["bars"]:
            r = match_intraday(o, m["bars"], start_ts, remaining, ctx["size_fn"], ctx["cfg"], o.get("triggered", False),
                               ctx.get("ext_cap_fn"))
            if r and r.get("too_small"):
                return ("reject", "too_small", r)
            if r:
                if remaining is not None:
                    r["total"] = r["total"] + done_qty
                return ("fill", {**r, "date": d, "precision": PRECISION.get(m["step"], f"{m['step']}초"),
                                 "sort_ts": r["first_ts"]})
            if closed:
                continue                                           # 그날은 끝났고 조건이 안 맞았다
            return None                                            # 장이 아직 열려 있을 수 있다 — 기다린다
        if closed and d >= elig_daily:
            typ = "market" if (o["type"] == "stop" and o.get("triggered")) else o["type"]
            price = match_daily({**o, "type": typ}, bars_by_date[d])
            if price is not None:
                return _daily_fill(o, d, price, remaining, ctx, _session_ts(d, market))
    last = max(bars_by_date) if bars_by_date else ""
    if last > o["valid_until"] or ctx["today"] > o["valid_until"]:
        return ("expire", f"유효기간({o['valid_until']})까지 조건이 맞지 않음")
    return None


def _daily_fill(o, d, price, remaining, ctx, ts):
    if remaining is None:
        remaining = ctx["size_fn"](price, ts)
        if remaining < 1:
            return ("reject", "too_small", {"price": price, "ts": ts})
    return ("fill", {"qty": remaining, "total": remaining + o.get("filled_qty", 0), "price": price,
                     "first_ts": None, "last_ts": None, "pieces": 1, "triggered": o.get("triggered", False),
                     "date": d, "precision": "하루", "sort_ts": ts, "session": "r"})
