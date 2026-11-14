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
print("\n전부 열림" if not fails else f"\n막힌 곳 {fails}군데")
sys.exit(1 if fails else 0)
