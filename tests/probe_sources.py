"""시세 원천이 이 컴퓨터(또는 클라우드)에서 열리는지 확인한다. 장부는 건드리지 않고, 아무것도 저장하지 않는다.

실행: python tests/probe_sources.py      (하나라도 실패하면 종료 코드 1)
"""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "broker"))
import prices as px  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
now = datetime.now(px.KST)
home = Path(tempfile.mkdtemp(prefix="paper_probe_"))
fails = 0


def probe(label, fn):
    global fails
    try:
        print(f"  열림  {label}: {fn()}")
    except Exception as e:
        fails += 1
        print(f"  막힘  {label}: {type(e).__name__} {str(e)[:120]}")


def daily(key):
    c = px.update(home, key, now)
    return f"{len(c['bars'])}일, 마지막 {c['bars'][-1]['d']} ({c['name']})"


def minutes(key):
    n1, n5 = px.update_minutes(home, key, now)
    ds = px.minute_dates(home, key)
    m = px.load_minutes(home, key, ds[-1])
    ses = sorted({b[6] for b in m["bars"] if len(b) > 6})
    return f"1분 {n1}일, 5분 {n5}일, 마지막 날 {ds[-1]} {len(m['bars'])}개, 시간대 {ses}"


def live(code):
    import live as lv
    d = lv.snapshot(code)
    return f"{d.get('stockName')} {d.get('closePrice')} · 시간외 {(d.get('overMarketPriceInfo') or {}).get('tradingSessionType')}"


def events(label_fn):
    ev = label_fn()
    dv, sp = ev["dividends"], ev["splits"]
    last = max(dv) if dv else None
    return (f"{ev.get('ticker') or ''} 종류 {ev.get('type')}, 최근 종가 {ev.get('close')}, 배당 {len(dv)}건 {sorted(dv.items())[-4:]}" + (f" (마지막 {last} 주당 {dv[last]})" if last else "")
            + f", 분할 {len(sp)}건" + (f" {sorted(sp.items())[-1]}" if sp else ""))


def kind(code):
    c = px.load(home, code) or px.update(home, code, now)
    return f"{c['name']} 종가 {c['bars'][-1]['c']} → {c.get('kind')} ({c.get('kind_src')}), 배당·분할 자료: {c.get('events_note')}"


print(f"시각 {now:%Y-%m-%d %H:%M} (한국)")
print("하루 시세")
probe("야후 미국 종목 (MU)", lambda: daily("MU"))
probe("야후 환율", lambda: daily(px.FX_KEY))
probe("다음 금융 한국 종목 (005930)", lambda: daily("005930"))
print("1분 시세")
probe("야후 미국 종목, 장전·장후 포함 (MU)", lambda: minutes("MU"))
probe("야후 환율", lambda: minutes(px.FX_KEY))
probe("네이버 한국 종목, 장후 포함 (005930)", lambda: minutes("005930"))
print("실시간 값 (장전 수집용)")
probe("네이버 실시간 (005930)", lambda: live("005930"))
print("배당·액면분할 (야후 events)")
probe("미국 종목 (AAPL, 5년)", lambda: events(lambda: px.fetch_yahoo_events("AAPL", "5y")))
probe("미국 종목 분할 (NVDA, 5년)", lambda: events(lambda: px.fetch_yahoo_events("NVDA", "5y")))
probe("한국 코스피 종목 (005930)", lambda: events(lambda: px.fetch_kr_events("005930")))
probe("한국 코스닥 종목 — 같은 번호의 다른 상품을 걸러 내는지 (247540)",
      lambda: events(lambda: px.fetch_kr_events("247540", px.update(home, "247540", now)["bars"][-1]["c"])))
probe("한국 ETF 분배금 (069500)", lambda: events(lambda: px.fetch_kr_events("069500")))
print("한국 종목이 ETF 인지 (매도 거래세가 다르다)")
probe("주식 (005930)", lambda: kind("005930"))
probe("ETF (069500)", lambda: kind("069500"))
probe("상표 목록에 없는 이름의 ETF (360750)", lambda: kind("360750"))
print("\n전부 열림" if not fails else f"\n막힌 곳 {fails}군데")
sys.exit(1 if fails else 0)
