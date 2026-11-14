"""가격·환율 수집과 캐시.

- 미국 종목·환율: 야후 chart API (일봉)
- 한국 종목: 다음 금융 일별 (KRX 정규장 종가 — 포털 '현재가'는 애프터마켓 가격이라 쓰지 않는다)
- 배당·액면분할: 야후 chart API 의 events (미국은 종목 기호 그대로, 한국은 {코드}.KS → 안 되면 .KQ).
  캐시의 "events": {"dividends": {배당락일: 주당 금액}, "splits": {분할일: [분자, 분모]}} 에 쌓는다 (지우지 않는다).
- 한국 종목이 ETF 인지("kind"): 야후 chart 응답의 종목 종류(instrumentType) → 없으면 이름의 운용사 상표로 어림. 매도 거래세가 ETF 는 없다.
캐시: {HOME}/data/prices/{키}.json  — 끝난 거래일의 봉만 넣는다.
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
FX_KEY = "USDKRW"


def market_of(symbol: str) -> str:
    return "KR" if re.fullmatch(r"\d{6}", symbol) else "US"


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def _complete(bar_date: str, market: str, now: datetime) -> bool:
    """그 날짜의 봉이 끝났는가 (now 는 KST)."""
    d = datetime.strptime(bar_date, "%Y-%m-%d").replace(tzinfo=KST)
    if market == "KR":
        return now >= d + timedelta(hours=16)            # 15:30 마감 뒤
    if market == "US":
        return now >= d + timedelta(days=1, hours=7)     # 다음 날 07:00 KST (서머타임 여부 무관)
    return now.date() > d.date()                          # 환율: 지난 날짜만


def _events(r, off):
    """야후 chart 응답의 배당·분할 사건을 {"dividends": {날짜: 금액}, "splits": {날짜: [분자, 분모]}} 로."""
    ev = r.get("events") or {}
    day = lambda ts: datetime.fromtimestamp(int(ts) + off, timezone.utc).strftime("%Y-%m-%d")
    out = {"dividends": {}, "splits": {}}
    for x in (ev.get("dividends") or {}).values():
        if x.get("amount"):
            out["dividends"][day(x["date"])] = x["amount"]
    for x in (ev.get("splits") or {}).values():
        if x.get("numerator") and x.get("denominator") and x["numerator"] != x["denominator"]:
            out["splits"][day(x["date"])] = [x["numerator"], x["denominator"]]
    return out


def fetch_yahoo_events(ticker: str, rng="2y"):
    """배당·분할 사건만 받는다 (한국 종목용 — 시세는 다른 곳에서 받는다). 종목 종류는 "type" 에 실어 준다."""
    j = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d&events=div%7Csplit")
    r = j["chart"]["result"][0]
    return {**_events(r, r["meta"].get("gmtoffset", 0)), "type": r["meta"].get("instrumentType")}


def fetch_kr_events(code: str):
    last = None
    for suffix in (".KS", ".KQ"):                       # 코스피 → 코스닥
        try:
            return fetch_yahoo_events(code + suffix)
        except Exception as e:
            last = e
    raise last


ETF_BRANDS = ("KODEX", "TIGER", "RISE", "KBSTAR", "ACE", "KINDEX", "PLUS", "ARIRANG", "SOL", "HANARO", "KOSEF", "KIWOOM",
              "TIMEFOLIO", "TIME", "WON", "1Q", "BNK", "FOCUS", "HK", "TRUSTON", "VITA", "KoAct", "TREX", "UNICORN", "ITF",
              "마이티", "파워", "에셋플러스", "히어로즈", "마이다스", "더제이", "WOORI", "DAISHIN343")


KIND_SRC = "야후 종목 종류"


def kr_kind(name: str, yahoo_type=None):
    """한국 종목이 ETF 인지. 반환 (kind, 근거). 야후가 알려 준 종목 종류가 없으면 이름의 운용사 상표로 어림한다."""
    t = str(yahoo_type or "").upper()
    if t:
        return ("etf" if t in ("ETF", "ETN", "MUTUALFUND") else "stock"), KIND_SRC
    return ("etf" if str(name).upper().startswith(tuple(b.upper() for b in ETF_BRANDS)) else "stock"), "이름으로 어림"


def fetch_yahoo(ticker: str, market: str, now: datetime, rng="6mo"):
    j = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d&events=div%7Csplit")
    r = j["chart"]["result"][0]
    off = r["meta"].get("gmtoffset", 0)
    q = r["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(r.get("timestamp") or []):
        c = q["close"][i]
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + off, timezone.utc).strftime("%Y-%m-%d")
        if not _complete(d, market, now):
            continue
        o, h, l = q["open"][i] or c, q["high"][i] or c, q["low"][i] or c
        bars.append({"d": d, "o": round(o, 4), "h": round(h, 4), "l": round(l, 4), "c": round(c, 4)})
    name = r["meta"].get("longName") or r["meta"].get("shortName") or ticker
    return bars, name, _events(r, off)


def fetch_daum(code: str, now: datetime, per=250):
    ref = {"Referer": f"https://finance.daum.net/quotes/A{code}"}
    j = _get(f"https://finance.daum.net/api/quote/A{code}/days?symbolCode=A{code}&page=1&perPage={per}&pagination=true", ref)
    bars = []
    for x in j.get("data", []):
        d = x["date"][:10]
        if not _complete(d, "KR", now) or not x.get("tradePrice"):
            continue
        c = x["tradePrice"]
        bars.append({"d": d, "o": x.get("openingPrice") or c, "h": x.get("highPrice") or c,
                     "l": x.get("lowPrice") or c, "c": c})
    bars.sort(key=lambda b: b["d"])
    name = code
    try:
        name = _get(f"https://finance.daum.net/api/quotes/A{code}?summary=false", ref).get("name") or code
    except Exception:
        pass
    return bars, name


def cache_path(home: Path, key: str) -> Path:
    return home / "data" / "prices" / f"{key}.json"


def load(home: Path, key: str):
    p = cache_path(home, key)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def update(home: Path, key: str, now: datetime):
    """key = 종목 기호 또는 FX_KEY. 새 봉을 캐시에 합친다. 종목이면 배당·분할 사건도 쌓는다."""
    old = load(home, key) or {"bars": []}
    events = {"dividends": dict((old.get("events") or {}).get("dividends") or {}),
              "splits": dict((old.get("events") or {}).get("splits") or {})}
    kind, kind_src, ev_note = old.get("kind"), old.get("kind_src"), old.get("events_note")
    new_ev = None
    if key == FX_KEY:
        market, ccy = "FX", "KRW"
        bars, name, _ = fetch_yahoo("KRW=X", "FX", now)
        name = "달러/원 환율"
    elif market_of(key) == "KR":
        market, ccy = "KR", "KRW"
        bars, name = fetch_daum(key, now)
        try:
            new_ev = fetch_kr_events(key)
            ev_note = "야후"
        except Exception as e:                           # 사건을 못 받아도 시세 갱신은 계속한다
            ev_note = f"받지 못함 ({type(e).__name__})"
        if kind_src != KIND_SRC or (new_ev or {}).get("type"):
            kind, kind_src = kr_kind(name, (new_ev or {}).get("type"))
    else:
        market, ccy = "US", "USD"
        bars, name, new_ev = fetch_yahoo(key, "US", now)
        ev_note = "야후"
        if set(new_ev["splits"]) - set(events["splits"]):   # 새 분할: 야후는 지난 값을 전부 고쳐 주므로 오래된 봉까지 다시 받는다
            try:
                bars = fetch_yahoo(key, "US", now, rng="10y")[0]
            except Exception:
                pass
    if new_ev:
        events["dividends"].update(new_ev["dividends"])
        events["splits"].update(new_ev["splits"])
    merged = {b["d"]: b for b in old["bars"]}
    for b in bars:
        merged[b["d"]] = b
    out = {"symbol": key, "market": market, "currency": ccy, "name": name,
           "updated": now.isoformat(timespec="seconds"),
           "source": "다음 금융 일별" if market == "KR" else "야후 일봉",
           "bars": [merged[d] for d in sorted(merged)]}
    if market != "FX":
        out["events"], out["events_note"] = events, ev_note
    if kind:
        out["kind"], out["kind_src"] = kind, kind_src
    p = cache_path(home, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def close_on_or_before(cache, date: str):
    """date 이하의 마지막 봉 (없으면 None)."""
    if not cache:
        return None
    best = None
    for b in cache["bars"]:
        if b["d"] <= date:
            best = b
        else:
            break
    return best


# ---------- 1분·5분 시세 ----------
# 봉 한 줄 = [시작 시각(epoch 초), 시가, 고가, 저가, 종가, 거래량, 시간대].  시간대: "r" 정규장 · "pre" 장전 · "post" 장후
# 날짜별 파일: data/minutes/{키}/{시장 현지 날짜}.json
# 1분 시세는 최근 8일치만 받을 수 있다 → 수집이 주 1~2회는 돌아야 빠진 날이 안 생긴다.
#   미국: 야후 — 장전 04:00~09:30, 정규장, 장후 16:00~20:00 (현지 시각). 장전·장후 봉에는 거래량이 없다.
#   한국: 네이버 — 정규장 09:00~15:30, 장후(넥스트레이드 애프터마켓) 15:40~20:00, 거래량 있음.
#         장전(넥스트레이드 프리마켓 08:00~08:50)의 지난 1분 시세는 무료로 받을 곳을 찾지 못했다 → broker/live.py 가 그 시간에 직접 모은다.
SESSION_KO = {"r": "정규장", "pre": "장전", "post": "장후"}


def _yahoo_intraday(ticker, interval, rng, now, utc_dates=False, prepost=False):
    j = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval={interval}"
             f"&includePrePost={'true' if prepost else 'false'}")
    r = j["chart"]["result"][0]
    off = 0 if utc_dates else r["meta"].get("gmtoffset", 0)
    q = r["indicators"]["quote"][0]
    step = 60 if interval == "1m" else 300
    limit = now.timestamp() - step                     # 끝난 봉만
    regular = []                                       # 날짜별 정규장 (시작, 끝)
    tp = r["meta"].get("tradingPeriods")
    if isinstance(tp, dict):
        for day in tp.get("regular", []):
            for x in day:
                regular.append((x["start"], x["end"]))
    elif isinstance(tp, list):
        for day in tp:
            for x in day:
                regular.append((x["start"], x["end"]))

    def session(ts):
        if not prepost:
            return "r"
        for a, b in regular:
            if a <= ts < b:
                return "r"
        if regular:
            day = [(a, b) for a, b in regular if abs(ts - a) < 16 * 3600]
            if day:
                return "pre" if ts < day[0][0] else "post"
        m = ((ts + off) % 86400) // 60                 # 정규장 표가 없을 때: 현지 시각으로
        return "pre" if m < 570 else ("post" if m >= 960 else "r")

    out = {}
    for i, ts in enumerate(r.get("timestamp") or []):
        c = q["close"][i]
        if c is None or ts > limit:
            continue
        d = datetime.fromtimestamp(ts + off, timezone.utc).strftime("%Y-%m-%d")
        o, h, l = q["open"][i] or c, q["high"][i] or c, q["low"][i] or c
        out.setdefault(d, []).append([ts, round(o, 4), round(h, 4), round(l, 4), round(c, 4), q["volume"][i] or 0, session(ts)])
    return out, step


def _naver_minutes(code, now):
    """한국 1분 시세. 정규장 09:00~15:19 와 15:30 종가 단일가는 "r", 15:40~20:00 은 "post"(넥스트레이드 애프터마켓)."""
    start = (now - timedelta(days=9)).strftime("%Y%m%d") + "0700"
    end = now.strftime("%Y%m%d%H%M")
    j = _get(f"https://api.stock.naver.com/chart/domestic/item/{code}/minute?startDateTime={start}&endDateTime={end}")
    limit = now.timestamp() - 60
    out = {}
    for x in j:
        s = x["localDateTime"]
        hm = s[8:12]
        if hm < "0800" or hm > "2000":
            continue
        ts = datetime.strptime(s[:12], "%Y%m%d%H%M").replace(tzinfo=KST).timestamp()
        if ts > limit:
            continue
        ses = "pre" if hm < "0900" else ("r" if hm <= "1530" else "post")
        d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        out.setdefault(d, []).append([int(ts), x["openPrice"], x["highPrice"], x["lowPrice"], x["currentPrice"],
                                      x["accumulatedTradingVolume"] or 0, ses])
    return out, 60


def minute_path(home: Path, key: str, d: str) -> Path:
    return home / "data" / "minutes" / key / f"{d}.json"


def load_minutes(home: Path, key: str, d: str):
    p = minute_path(home, key, d)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def minute_dates(home: Path, key: str):
    p = home / "data" / "minutes" / key
    return sorted(f.stem for f in p.glob("*.json")) if p.exists() else []


def _save_minutes(home, key, days, step, src):
    n = 0
    for d, bars in days.items():
        old = load_minutes(home, key, d)
        if old and old["step"] < step:
            continue                                    # 더 촘촘한 것이 이미 있다
        merged = {b[0]: b for b in (old["bars"] if old and old["step"] == step else [])}
        for b in bars:
            merged[b[0]] = b
        p = minute_path(home, key, d)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"step": step, "src": src, "bars": [merged[t] for t in sorted(merged)]}), encoding="utf-8")
        n += 1
    return n


def update_minutes(home: Path, key: str, now: datetime):
    """1분 시세(장전·장후 포함)를 받아 날짜별로 합친다. 미국 종목은 1분이 없는 최근 날짜를 5분으로 메운다.
    반환: (1분 날짜 수, 5분 날짜 수)"""
    if key == FX_KEY:
        days, step = _yahoo_intraday("KRW=X", "1m", "8d", now, utc_dates=True)
        return _save_minutes(home, key, days, step, "야후 1분"), 0
    if market_of(key) == "KR":
        days, step = _naver_minutes(key, now)
        return _save_minutes(home, key, days, step, "네이버 1분"), 0
    days, step = _yahoo_intraday(key, "1m", "8d", now, prepost=True)
    n1 = _save_minutes(home, key, days, step, "야후 1분")
    days5, step5 = _yahoo_intraday(key, "5m", "60d", now)
    have = set(minute_dates(home, key))
    n5 = _save_minutes(home, key, {d: b for d, b in days5.items() if d not in have}, step5, "야후 5분")
    return n1, n5


def last_trade(home: Path, key: str):
    """가장 최근에 거래된 값 (시간외 포함). 반환 {price, ts, session} 또는 None."""
    ds = minute_dates(home, key)
    if not ds:
        return None
    m = load_minutes(home, key, ds[-1])
    if not m or not m["bars"]:
        return None
    b = m["bars"][-1]
    return {"price": b[4], "ts": b[0], "session": b[6] if len(b) > 6 else "r"}


def fx_at(home: Path, ts: float, daily):
    """그 시각의 달러/원. 1분 환율이 있으면 그 시각 직전 값, 없으면 그 날짜 이하의 일별 종가."""
    d = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    m = load_minutes(home, FX_KEY, d)
    if m:
        best = None
        for b in m["bars"]:
            if b[0] <= ts:
                best = b
            else:
                break
        if best:
            return best[4], "1분"
    kd = datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")
    b = close_on_or_before(daily, kd)
    return (b["c"], "하루") if b else (None, None)
