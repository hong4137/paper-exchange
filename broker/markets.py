"""장이 열리는 때 — 한국(KRX·넥스트레이드)과 미국(NYSE·나스닥)의 휴장일·시간대·서머타임.

운용자(일지 도구)가 휴장일·서머타임을 계산하지 않도록 거래소가 state.json 에 지금 상태와 다음 개장·폐장 시각을 싣는다.
시각은 모두 한국 시각(+09:00)으로 낸다.

시간대 (거래소가 체결에 쓰는 것과 같다)
  한국: 장전 08:00~08:50 (넥스트레이드 프리마켓) · 정규장 09:00~15:30 · 장후 15:40~20:00 (넥스트레이드 애프터마켓)
  미국(뉴욕 시각): 장전 04:00~09:30 · 정규장 09:30~16:00 · 장후 16:00~20:00. 조기 폐장일은 정규장 13:00, 장후 17:00 까지.
  서머타임: 3월 둘째 일요일 02:00 ~ 11월 첫째 일요일 02:00 (뉴욕 시각). 그동안 뉴욕 = 한국 − 13시간, 아니면 − 14시간.
  환율: 주말을 빼고 늘 열린다고 본다 (뉴욕 금요일 17:00 ~ 일요일 17:00 닫힘).

휴장일 표 — 2026~2028년. 출처: 파이썬 holidays 0.108 의 KRX·NYSE 거래소 달력(2026-11-15 뽑음, 주말 제외).
  표에 없는 해는 주말만 쉰다고 보고 calendar_ok=False 로 알린다 — 2028년 말 전에 표를 늘려야 한다.
  한국의 시간이 바뀌는 날(수능일·새해 첫 거래일)은 KR_SPECIAL 표를 쓴다 — 아래 설명.
  임시공휴일·임시 휴장은 KR_HOLIDAYS / US_HOLIDAYS 에, 시간이 바뀌는 날은 KR_SPECIAL 에 손으로 한 줄 더한다(사람이 알려 주면).
  한국 시간대를 정하는 곳은 이 파일 하나다 — prices.py(1분 봉의 시간대 표시·하루 시세가 끝났는지)·matching.py(하루 시세 어림)도 여기서 받는다.
"""
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))
CAL_YEARS = range(2026, 2029)

KR_HOLIDAYS = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02", "2026-05-01", "2026-05-05", "2026-05-25",
    "2026-06-03", "2026-07-17", "2026-08-17", "2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09", "2026-12-25",
    "2026-12-31",
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-01", "2027-05-03", "2027-05-05", "2027-05-13", "2027-07-19",
    "2027-08-16", "2027-09-14", "2027-09-15", "2027-09-16", "2027-10-04", "2027-10-11", "2027-12-27", "2027-12-31",
    "2028-01-26", "2028-01-27", "2028-01-28", "2028-03-01", "2028-04-12", "2028-05-01", "2028-05-02", "2028-05-05",
    "2028-06-06", "2028-07-17", "2028-08-15", "2028-10-02", "2028-10-03", "2028-10-04", "2028-10-05", "2028-10-09",
    "2028-12-25", "2028-12-29",
}
US_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04", "2028-11-23",
    "2028-12-25",
}
# 한국의 시간이 바뀌는 날 — 날짜: {why, pre, r, post (각각 ("HH:MM", "HH:MM") 또는 None = 열리지 않음), src, status}
# 2026-11-15 조사. "확인" = 거래소·넥스트레이드 발표 보도 여럿이 일치, "예상" = 아직 공지 전이라 그해 관례대로 넣음(공지가 나오면 고친다).
#   새해 첫 거래일: KRX 정규장 10:00 개장(개장식), 마감은 평소대로 15:30. 넥스트레이드 프리마켓 없음, 메인마켓 10:00:30 시작·평소 마감.
#     출처(2026-01-02): kukinews.com/article/view/kuk202601020012 · s-d.kr/news/articleView.html?idxno=78564 · newscj.com/news/articleView.html?idxno=3358560
#     애프터마켓(15:40~20:00)이 그날 그대로인지는 기사에 없다 — 확인 못 함, 평소대로 넣었다.
#   수능일: KRX 정규장 10:00~16:30 (한 시간씩 늦춤). 넥스트레이드 프리마켓 없음, 애프터마켓 17:00~20:00 (시작만 한 시간 늦춤).
#     출처(2026-11-19, 거래소 2026-11-05 발표): ebn.co.kr/news/articleView.html?idxno=1730562 · dt.co.kr/article/12093371 · news.mtn.co.kr/article/2026110510425587061
#     넥스트레이드 메인마켓이 16:20 까지라는 보도가 한 곳(newswell.co.kr idxno=23446)에만 있다 — 거래소는 KRX 시간(16:30)을 쓴다.
#   수능 날짜: 2027-11-18(2028학년도), 2028-11-16(2029학년도) — 교육부 발표(sanedu.com 입시리포트 등). 시장 시간은 그해 거래소 공지 전이라 "예상".
KR_SPECIAL = {
    "2026-01-02": {"why": "새해 첫 거래일", "pre": None, "r": ("10:00", "15:30"), "post": ("15:40", "20:00"), "status": "확인 (장후는 확인 못 함)"},
    "2026-11-19": {"why": "수능일", "pre": None, "r": ("10:00", "16:30"), "post": ("17:00", "20:00"), "status": "확인"},
    "2027-01-04": {"why": "새해 첫 거래일", "pre": None, "r": ("10:00", "15:30"), "post": ("15:40", "20:00"), "status": "예상"},
    "2027-11-18": {"why": "수능일", "pre": None, "r": ("10:00", "16:30"), "post": ("17:00", "20:00"), "status": "예상"},
    "2028-01-03": {"why": "새해 첫 거래일", "pre": None, "r": ("10:00", "15:30"), "post": ("15:40", "20:00"), "status": "예상"},
    "2028-11-16": {"why": "수능일", "pre": None, "r": ("10:00", "16:30"), "post": ("17:00", "20:00"), "status": "예상"},
}
KR_NORMAL = {"pre": ("08:00", "08:50"), "r": ("09:00", "15:30"), "post": ("15:40", "20:00")}

US_EARLY_CLOSE = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}   # 정규장 13:00 폐장

LABEL = {"pre": "장전", "r": "정규장", "post": "장후", "closed": "닫힘"}


def _nth_sunday(y, m, n):
    d = date(y, m, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def ny_offset(d):
    """그날 뉴욕 시각의 UTC 차이(시간). 서머타임이면 -4, 아니면 -5."""
    return -4 if _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1) else -5


def is_trading_day(market, d):
    """그 시장 현지 날짜 d(date)가 정규장이 열리는 날인가."""
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in (KR_HOLIDAYS if market == "KR" else US_HOLIDAYS)


def calendar_ok(d):
    return d.year in CAL_YEARS


def sessions(market, d):
    """현지 날짜 d 의 시간대 목록 [(이름, 시작, 끝)] — 한국 시각의 datetime. 쉬는 날이면 []."""
    if not is_trading_day(market, d):
        return []
    if market == "KR":
        plan = KR_SPECIAL.get(d.isoformat(), KR_NORMAL)
        at = lambda hm: datetime.combine(d, time(int(hm[:2]), int(hm[3:])), KST)
        return [(n, at(plan[n][0]), at(plan[n][1])) for n in ("pre", "r", "post") if plan.get(n)]
    tz = timezone(timedelta(hours=ny_offset(d)))
    at = lambda hh, mm: datetime.combine(d, time(hh, mm), tz).astimezone(KST)
    early = d.isoformat() in US_EARLY_CLOSE
    close = at(13, 0) if early else at(16, 0)
    return [("pre", at(4, 0), at(9, 30)), ("r", at(9, 30), close), ("post", close, at(17, 0) if early else at(20, 0))]


def regular(market, d):
    """현지 날짜 d 의 정규장 (시작, 끝) — 한국 시각 datetime. 쉬는 날이면 None."""
    return next(((s, e) for n, s, e in sessions(market, d) if n == "r"), None)


def kr_session_of(ts):
    """한국 1분 봉(시작 시각 epoch 초)의 시간대: "pre"·"r"·"post". 그날 시간표 밖이면 정규장 앞은 "pre", 뒤는 "post"
    (수능일 15:31~16:30 은 "r", 새해 첫날 09:00~09:59 는 "pre" — 정규장이 아니다)."""
    t = datetime.fromtimestamp(ts, KST)
    for n, s, e in sessions("KR", t.date()):
        if s <= t < e or (n == "r" and t == e):          # 정규장 끝 시각의 봉(마감 단일가)은 정규장
            return n
    r = regular("KR", t.date())
    if r:
        return "pre" if t < r[0] else "post"
    return "pre" if t.hour < 9 else "post"


def special(d):
    """그날이 한국의 시간이 바뀌는 날이면 그 설명 dict, 아니면 None."""
    x = KR_SPECIAL.get(d.isoformat() if hasattr(d, "isoformat") else str(d))
    return {"date": d.isoformat() if hasattr(d, "isoformat") else str(d), **{k: (list(v) if isinstance(v, tuple) else v) for k, v in x.items()}} if x else None


def _local_date(market, t):
    if market == "KR":
        return t.astimezone(KST).date()
    u = t.astimezone(timezone.utc)
    return (u + timedelta(hours=ny_offset((u - timedelta(hours=5)).date()))).date()


def _iter_sessions(market, t, days=15):
    """t 가 속한 현지 날짜(하루 앞부터)부터 시간대를 차례로."""
    d0 = _local_date(market, t) - timedelta(days=1)
    for i in range(days):
        yield from sessions(market, d0 + timedelta(days=i))


def status(market, t):
    """지금(t) 그 시장의 상태와 다음 개장·폐장. 반환 dict:
    state(pre|r|post|closed) · label(장전·정규장·장후·닫힘) · session_ends(지금 시간대가 끝나는 때, 닫힘이면 None) ·
    next_open(다음 정규장 시작 — 정규장 중이면 그다음 날 것) · next_close(지금 정규장이면 오늘 폐장, 아니면 다음 정규장의 폐장) ·
    trading_day(지금 또는 다음 정규장의 현지 날짜) · calendar_ok"""
    if market == "FX":
        u = t.astimezone(timezone.utc)
        ny = u + timedelta(hours=ny_offset(u.date()))
        wd, h = ny.weekday(), ny.hour
        shut = (wd == 4 and h >= 17) or wd == 5 or (wd == 6 and h < 17)
        if shut:
            days = (6 - wd) % 7
            reopen = datetime.combine(ny.date() + timedelta(days=days), time(17, 0),
                                      timezone(timedelta(hours=ny_offset(ny.date() + timedelta(days=days))))).astimezone(KST)
            return {"state": "closed", "label": "닫힘", "session_ends": None, "next_open": reopen.isoformat(timespec="minutes"),
                    "next_close": None, "trading_day": None, "calendar_ok": True}
        return {"state": "r", "label": "열림 (주말 빼고 늘)", "session_ends": None, "next_open": None, "next_close": None,
                "trading_day": None, "calendar_ok": True}
    cur, nxt_open, nxt_close, day = None, None, None, None
    for name, s, e in _iter_sessions(market, t):
        if s <= t < e and cur is None:
            cur = (name, e)
        if name == "r":
            if s > t and nxt_open is None:
                nxt_open = s
            if e > t and nxt_close is None:
                nxt_close, day = e, _local_date(market, s)
        if nxt_open and nxt_close:
            break
    state = cur[0] if cur else "closed"
    return {"state": state, "label": LABEL[state], "session_ends": cur[1].isoformat(timespec="minutes") if cur else None,
            "next_open": nxt_open.isoformat(timespec="minutes") if nxt_open else None,
            "next_close": nxt_close.isoformat(timespec="minutes") if nxt_close else None,
            "trading_day": day.isoformat() if day else None, "calendar_ok": calendar_ok(_local_date(market, t)),
            "special": special(day) if (market == "KR" and day) else None}


def _next_minute(t):
    t = t.astimezone(KST)
    return (t.replace(second=0, microsecond=0) + timedelta(minutes=1))


def earliest_fill(o, t):
    """주문 o 가 시각 t(접수 시각과 지금 중 늦은 쪽) 뒤에 가장 빨리 체결될 수 있는 때 (한국 시각 datetime). 모르면 None.
    체결 규칙(matching.py)과 같게: 주문 뒤에 시작한 1분부터. 시장가·손절 = 정규장, 지정가 = 정규장(시간외 포함이면 장전·장후도),
    종가 = 그날(또는 다음) 정규장 폐장. 지정가·손절은 값이 닿아야 체결되므로 '이때부터 체결될 수 있다'는 뜻이다."""
    market = o.get("market")
    start = _next_minute(t)
    if market == "FX":
        st = status("FX", start)
        return start if st["state"] == "r" else datetime.fromisoformat(st["next_open"])
    if market not in ("KR", "US"):
        return None
    typ = o.get("type") or "market"
    ok = {"pre", "r", "post"} if (typ == "limit" and o.get("session") == "all") else {"r"}
    for name, s, e in _iter_sessions(market, start):
        if name not in ok or e <= start:
            continue
        if typ == "moc":
            return e if name == "r" else None
        return max(s, start)
    return None


# 정기 실행을 부르는 바깥 깨우미(통합 개발/경제브리핑/gas-waker.gs 의 "모의 거래소 정기 실행")와 같은 규칙. 그쪽을 바꾸면 여기도 맞춘다.
# 정한 시각(서울)에 한 번씩 + 장중에는 20분 칸마다 한 번. 깨우미는 10분마다 깨어나므로 실제로는 그 시각부터 10분 안에 돈다.
# 칸의 요일은 그 시간대가 시작한 날의 요일이다(미국장 22:30~06:00 은 월~금 밤에 시작한 것만). 휴장일은 따지지 않는다.
WAKE_TIMES = ["06:20", "07:20", "16:20", "20:20", "21:20", "22:20"]
WAKE_EVERY = [{"minutes": 20, "from": "09:00", "to": "15:40", "weekdays": [1, 2, 3, 4, 5]},
              {"minutes": 20, "from": "22:30", "to": "06:00", "weekdays": [1, 2, 3, 4, 5]}]
WAKE_GRACE_MIN = 10


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _wake_cell(c):
    """시각 c 가 장중 칸 안이면 그 칸 [(날짜, 칸 번호)], 아니면 []."""
    m, wd = c.hour * 60 + c.minute, c.isoweekday()
    out = []
    for w in WAKE_EVERY:
        a, b = _hm(w["from"]), _hm(w["to"])
        if a <= b:
            inside, start_wd = a <= m < b, wd
        elif m >= a:
            inside, start_wd = True, wd
        else:
            inside, start_wd = m < b, (wd - 2) % 7 + 1
        if inside and start_wd in w["weekdays"]:
            out.append((c.date(), m // w["minutes"]))
    return out


def next_wake(t):
    """바깥 깨우미가 정기 실행을 다음에 부를 시각(그 시각부터 10분 안에 돈다). 반환 datetime(서울).
    지금 장중 칸 안이면 그 칸은 이미 불린 것으로 보고 다음 칸부터 찾는다."""
    t = t.astimezone(KST).replace(second=0, microsecond=0)
    done = set(_wake_cell(t))
    for i in range(1, 3 * 24 * 60):
        c = t + timedelta(minutes=i)
        if any(c.hour * 60 + c.minute == _hm(s) for s in WAKE_TIMES):
            return c
        if any(x not in done for x in _wake_cell(c)):
            return c
    return None


def next_cron(t, minute=7):
    """매시 minute 분에 도는 정기 실행의 다음 예정 시각 (GitHub 예약은 몇 분~몇십 분 늦을 수 있다)."""
    t = t.astimezone(KST)
    c = t.replace(minute=minute, second=0, microsecond=0)
    return c if c > t else c + timedelta(hours=1)
