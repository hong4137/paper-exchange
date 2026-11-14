"""한국 장전(넥스트레이드 프리마켓 08:00~08:50) 시세를 그 시간에 직접 모은다.

왜: 한국 장전의 지난 1분 시세는 무료로 받을 곳을 찾지 못했다(네이버 1분 시세는 09:00 부터).
    네이버 실시간 값에는 시간외 가격이 들어 있으므로, 장전 시간에 15초마다 읽어 1분 시세를 직접 만든다.
쓰는 법 (평일 07:58 쯤 시작):
  python broker/live.py --minutes 55                  보유 종목과 살아 있는 주문의 한국 종목
  python broker/live.py --minutes 55 --symbols 005930,000660
읽은 원본은 data/live_raw/{날짜}.jsonl 에 그대로 남긴다 (해석이 틀렸을 때 다시 만들 수 있게).

⚠ 2026-11-14(토)에 만들어 장전 시간에 실제로 돌려 보지 못했다. 장후(AFTER_MARKET) 값의 모양으로 미루어 짰다.
   첫 평일 아침에 돌려 data/live_raw 를 보고 맞는지 확인할 것.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prices as px  # noqa: E402

HOME = Path(os.environ.get("PAPER_HOME") or Path(__file__).resolve().parent.parent)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def snapshot(code):
    j = px._get(f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}")
    return j["datas"][0]


def default_symbols():
    led = HOME / "ledger" / "ledger.jsonl"
    if not led.exists():
        return []
    import broker                                      # 장부를 읽기만 한다
    st = broker.replay(broker.read_ledger())
    syms = {o["symbol"] for o in st["orders"].values() if o["status"] in broker.OPEN} | {s for s, l in st["lots"].items() if l}
    return sorted(s for s in syms if px.market_of(s) == "KR")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=55)
    ap.add_argument("--symbols")
    ap.add_argument("--every", type=float, default=15, help="몇 초마다 읽을지")
    ap.add_argument("--any-session", action="store_true", help="장전이 아니어도 시간외 값을 봉으로 만든다 (시험용)")
    a = ap.parse_args()
    syms = [s.strip() for s in a.symbols.split(",")] if a.symbols else default_symbols()
    if not syms:
        print("모을 한국 종목이 없습니다.")
        return
    print("모으는 종목:", ", ".join(syms))
    bars, last_vol, n_raw = {}, {}, 0                   # bars[종목][분 시작 epoch] = [t,o,h,l,c,v,"pre"]
    end = time.time() + a.minutes * 60
    while time.time() < end:
        now = datetime.now(px.KST)
        raw_path = HOME / "data" / "live_raw" / f"{now:%Y-%m-%d}.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        for s in syms:
            try:
                d = snapshot(s)
            except Exception as e:
                print(f"  {s} 읽기 실패: {type(e).__name__}")
                continue
            over = d.get("overMarketPriceInfo") or {}
            with raw_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": now.isoformat(timespec="seconds"), "symbol": s,
                                    "marketSessionType": d.get("marketSessionType"), "marketStatus": d.get("marketStatus"),
                                    "closePrice": d.get("closePrice"), "over": over}, ensure_ascii=False) + "\n")
            n_raw += 1
            kind = over.get("tradingSessionType")
            is_open = over.get("overMarketStatus") == "OPEN"
            if not ((kind == "PRE_MARKET" and is_open) or a.any_session):
                continue
            price = num(over.get("overPrice"))
            if not price:
                continue
            t = int(now.timestamp() // 60 * 60)
            vol_now = num(over.get("accumulatedTradingVolumeRaw") or over.get("accumulatedTradingVolume"))
            dv = max(0, int(vol_now - last_vol[s])) if vol_now is not None and s in last_vol else 0
            if vol_now is not None:
                last_vol[s] = vol_now
            b = bars.setdefault(s, {}).get(t)
            if b:
                b[2], b[3], b[4], b[5] = max(b[2], price), min(b[3], price), price, b[5] + dv
            else:
                bars[s][t] = [t, price, price, price, price, dv, "pre"]
        for s, by_t in bars.items():                    # 읽을 때마다 저장 — 중간에 꺼져도 남는다
            done = [b for t, b in by_t.items() if t + 60 <= time.time()]
            if done:
                d = datetime.fromtimestamp(done[0][0], px.KST).strftime("%Y-%m-%d")
                px._save_minutes(HOME, s, {d: done}, 60, "네이버 1분")
        time.sleep(a.every)
    print(f"끝. 원본 {n_raw}줄, 만든 1분 시세: " + (", ".join(f"{s} {len(v)}개" for s, v in bars.items()) or "없음 (장전 시간이 아니었음)"))


if __name__ == "__main__":
    main()
