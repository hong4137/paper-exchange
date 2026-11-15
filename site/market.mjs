// 주문 페이지의 시장 정보 — 시장 현황, 종목 검색, 종목 현황. 문지기(lib.mjs)가 로그인한 사람에게만 내준다.
//
// 볼 때마다 원천에서 바로 가져온다 (사용자 결정 2026-11-15: "볼 때마다 실시간"). 같은 값은 짧게(30초) 기억해 둔다.
//   지수·환율·금리·원자재, 미국 종목: 야후 chart API (거래소의 prices.py 와 같은 원천)
//   한국 종목: 네이버 실시간(polling.finance.naver.com — broker/live.py 와 같은 원천) + 네이버 1분 시세(api.stock.naver.com — prices.py 와 같은 원천)
//   검색: 네이버 자동완성(한국 종목·한글 이름) + 야후 검색(미국 종목)
// 응답 모양은 2026-11-15 GitHub 확인 실행(tests/probe_market.mjs)으로 실제 원천에서 확인했다 — 네이버 자동완성 {query, items:[{code, name, typeName, reutersCode, nationCode, category}]},
//   네이버 실시간 datas[0] {stockName, closePrice "209,000", compareToPreviousClosePrice(부호 없음 — compareToPreviousPrice.name 이 RISING/FALLING), openPrice…, marketStatus, overMarketPriceInfo}.
//   원천이 바뀌면 그 원천을 읽는 함수 하나만 고친다.
// 여기 값은 화면에 보여 주는 참고용이다. 체결은 거래소가 주문 뒤의 1분 시세로 따로 계산한다.

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36';
const TTL = 30 * 1000;
const memo = new Map();
export function _resetMarket() { memo.clear(); }

async function getJSON(url, fetchFn, headers = {}) {
  const hit = memo.get(url);
  if (hit && Date.now() - hit.at < TTL) return hit.v;
  const r = await fetchFn(url, { headers: { 'user-agent': UA, accept: 'application/json', ...headers }, cf: { cacheTtl: 20 } });
  if (!r.ok) throw new Error(`원천 응답 ${r.status}`);
  const v = await r.json();
  memo.set(url, { at: Date.now(), v });
  if (memo.size > 300) memo.delete(memo.keys().next().value);
  return v;
}

const num = (v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(String(v).replace(/,/g, ''));
  return Number.isFinite(n) ? n : null;
};
const round = (v, d = 4) => (v === null || v === undefined ? null : Math.round(v * 10 ** d) / 10 ** d);
const chg = (price, prev) => (price !== null && prev ? { chg: round(price - prev), chg_pct: round((price / prev - 1) * 100, 2) } : { chg: null, chg_pct: null });

// ---------- 시장 현황 ----------
export const OVERVIEW = [
  { key: 'kospi', label: '코스피', group: '한국', y: '^KS11' },
  { key: 'kosdaq', label: '코스닥', group: '한국', y: '^KQ11' },
  { key: 'spx', label: 'S&P500', group: '미국', y: '^GSPC' },
  { key: 'ixic', label: '나스닥', group: '미국', y: '^IXIC' },
  { key: 'dji', label: '다우', group: '미국', y: '^DJI' },
  { key: 'es', label: 'S&P500 선물', group: '미국', y: 'ES=F' },
  { key: 'nq', label: '나스닥100 선물', group: '미국', y: 'NQ=F' },
  { key: 'n225', label: '닛케이225', group: '아시아·유럽', y: '^N225' },
  { key: 'sse', label: '상해종합', group: '아시아·유럽', y: '000001.SS' },
  { key: 'hsi', label: '항셍', group: '아시아·유럽', y: '^HSI' },
  { key: 'sx5e', label: '유로스톡스50', group: '아시아·유럽', y: '^STOXX50E' },
  { key: 'usdkrw', label: '달러/원', group: '환율·금리·원자재', y: 'KRW=X', unit: '원' },
  { key: 'tnx', label: '미국 10년 국채 금리', group: '환율·금리·원자재', y: '^TNX', unit: '%', rate: true },
  { key: 'wti', label: '국제 유가 (WTI)', group: '환율·금리·원자재', y: 'CL=F', unit: '달러' },
  { key: 'gold', label: '금', group: '환율·금리·원자재', y: 'GC=F', unit: '달러' },
];

const yahooChart = (sym, range, interval, prepost) =>
  `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=${interval}&includePrePost=${prepost ? 'true' : 'false'}`;

/** 야후 chart 응답 → { name, price, prev, time, currency, bars:[[t, close, volume]], periods } */
export function readYahooChart(j) {
  const r = j && j.chart && Array.isArray(j.chart.result) ? j.chart.result[0] : null;
  if (!r || !r.meta) throw new Error('야후 응답 모양이 다릅니다');
  const m = r.meta;
  const q = (r.indicators && r.indicators.quote && r.indicators.quote[0]) || {};
  const ts = r.timestamp || [];
  const bars = [];
  for (let i = 0; i < ts.length; i++) {
    const c = num((q.close || [])[i]);
    if (c !== null) bars.push([ts[i], c, num((q.volume || [])[i]) || 0, num((q.open || [])[i]), num((q.high || [])[i]), num((q.low || [])[i])]);
  }
  const price = num(m.regularMarketPrice) ?? (bars.length ? bars[bars.length - 1][1] : null);
  const prev = num(m.previousClose) ?? num(m.chartPreviousClose);
  return { name: m.longName || m.shortName || m.symbol, price, prev, time: num(m.regularMarketTime), currency: m.currency,
           exchange: m.fullExchangeName || m.exchangeName, type: m.instrumentType,
           volume: num(m.regularMarketVolume), dayHigh: num(m.regularMarketDayHigh), dayLow: num(m.regularMarketDayLow),
           periods: m.currentTradingPeriod || null, bars };
}

export async function overview(fetchFn = fetch) {
  const items = await Promise.all(OVERVIEW.map(async (o) => {
    try {
      let c = readYahooChart(await getJSON(yahooChart(o.y, '1d', '5m', false), fetchFn));
      if (c.bars.length < 2) {      // 선물·원자재는 쉬는 날 "오늘"이 비어 있다 — 최근 며칠 것을 받아 가장 최근 거래일만 쓴다
        const w = readYahooChart(await getJSON(yahooChart(o.y, '5d', '15m', false), fetchFn));
        const lastDay = w.bars.length ? Math.floor((w.bars[w.bars.length - 1][0] + 9 * 3600) / 86400) : null;
        c = { ...c, bars: w.bars.filter((b) => Math.floor((b[0] + 9 * 3600) / 86400) === lastDay), price: c.price ?? w.price, prev: c.prev ?? w.prev };
      }
      let { price, prev } = c;
      let spark = c.bars.map((b) => b[1]);
      if (o.rate && price > 20) { price /= 10; prev = prev && prev / 10; spark = spark.map((v) => v / 10); }   // 옛 표기(금리×10) 대비
      const d = o.rate ? { chg: price !== null && prev ? round(price - prev, 3) : null, chg_pct: null } : chg(price, prev);
      return { key: o.key, label: o.label, group: o.group, unit: o.unit || null, rate: !!o.rate, price: round(price, 4), prev: round(prev, 4),
               ...d, time: c.time, spark: thin(spark, 60) };
    } catch (e) {
      return { key: o.key, label: o.label, group: o.group, error: '값을 받지 못했습니다' };
    }
  }));
  return { at: Math.floor(Date.now() / 1000), items };
}

function thin(arr, n) {
  if (arr.length <= n) return arr.map((v) => round(v, 4));
  const out = [];
  for (let i = 0; i < n; i++) out.push(round(arr[Math.round((i * (arr.length - 1)) / (n - 1))], 4));
  return out;
}

// ---------- 종목 검색 ----------
const KR_CODE = /^\d{6}$/;
const US_SYM = /^[A-Z][A-Z0-9.\-]{0,9}$/;

/** 네이버 자동완성 응답에서 종목 목록을 꺼낸다. 모양을 몰라 배열 속 {code|cd, name|nm} 를 넓게 찾는다. */
export function readNaverSearch(j) {
  const out = [];
  const visit = (x, depth) => {
    if (!x || depth > 4) return;
    if (Array.isArray(x)) { x.forEach((y) => visit(y, depth + 1)); return; }
    if (typeof x !== 'object') return;
    const code = x.code ?? x.cd ?? x.itemCode ?? x.symbolCode;
    const name = x.name ?? x.nm ?? x.stockName ?? x.itemName;
    if (code && name) {
      const nation = String(x.nationCode ?? x.nation ?? '').toUpperCase();
      const cat = String(x.category ?? x.typeCode ?? x.type ?? '').toLowerCase();
      if (KR_CODE.test(String(code)) && (!nation || nation === 'KOR')) {
        out.push({ symbol: String(code), name: String(name), market: 'KR', exchange: x.typeName || x.typeCode || '한국', kind: /etf|etn/.test(cat) ? 'ETF' : null });
      } else if (nation && nation !== 'KOR') {
        const sym = String(x.reutersCode ?? code).split('.')[0].toUpperCase();
        if (US_SYM.test(sym) && /USA|US/.test(nation)) out.push({ symbol: sym, name: String(name), market: 'US', exchange: x.typeName || '미국' });
      }
      return;
    }
    Object.values(x).forEach((y) => visit(y, depth + 1));
  };
  visit(j, 0);
  return out;
}

const US_EXCH = new Set(['NMS', 'NGM', 'NCM', 'NYQ', 'NYS', 'ASE', 'PCX', 'BTS', 'NAS', 'NYSE', 'NASDAQ', 'AMEX']);

/** 야후 검색 응답에서 미국 주식·ETF 를 꺼낸다. */
export function readYahooSearch(j) {
  const out = [];
  for (const q of (j && Array.isArray(j.quotes) ? j.quotes : [])) {
    const sym = String(q.symbol || '').toUpperCase();
    const type = String(q.quoteType || '').toUpperCase();
    if (!['EQUITY', 'ETF'].includes(type)) continue;
    const m = /^(\d{6})\.(KS|KQ)$/.exec(sym);
    if (m) { out.push({ symbol: m[1], name: q.shortname || q.longname || m[1], market: 'KR', exchange: m[2] === 'KS' ? '코스피' : '코스닥', kind: type === 'ETF' ? 'ETF' : null }); continue; }
    if (!US_SYM.test(sym) || (q.exchange && !US_EXCH.has(String(q.exchange).toUpperCase()))) continue;
    out.push({ symbol: sym, name: q.longname || q.shortname || sym, market: 'US', exchange: q.exchDisp || q.exchange || '미국', kind: type === 'ETF' ? 'ETF' : null });
  }
  return out;
}

export async function search(qRaw, fetchFn = fetch) {
  const q = String(qRaw || '').trim().slice(0, 40);
  if (!q) return { items: [] };
  const tasks = [
    getJSON(`https://ac.stock.naver.com/ac?q=${encodeURIComponent(q)}&target=stock`, fetchFn).then(readNaverSearch).catch(() => []),
  ];
  if (/[A-Za-z]/.test(q)) {
    tasks.push(getJSON(`https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(q)}&quotesCount=10&newsCount=0&listsCount=0`, fetchFn)
      .then(readYahooSearch).catch(() => []));
  }
  const lists = await Promise.all(tasks);
  const seen = new Set(), items = [];
  const add = (x) => { const k = x.market + ':' + x.symbol; if (!seen.has(k)) { seen.add(k); items.push(x); } };
  if (KR_CODE.test(q)) add({ symbol: q, name: q, market: 'KR', exchange: '한국', direct: true });
  for (const l of lists) l.forEach(add);
  if (q.length <= 5 && US_SYM.test(q.toUpperCase()) && !items.some((x) => x.symbol === q.toUpperCase())) add({ symbol: q.toUpperCase(), name: q.toUpperCase(), market: 'US', exchange: '미국', direct: true });
  return { items: items.slice(0, 15) };
}

// ---------- 종목 현황 ----------
const KST = 9 * 3600;
const kstHM = (t) => { const d = new Date((t + KST) * 1000); return d.getUTCHours() * 100 + d.getUTCMinutes(); };
const kstDay = (t) => new Date((t + KST) * 1000).toISOString().slice(0, 10).replace(/-/g, '');

/** 네이버 실시간 응답 → 한국 종목 현황. */
export function readNaverRealtime(j) {
  const d = j && Array.isArray(j.datas) ? j.datas[0] : null;
  if (!d) throw new Error('네이버 응답 모양이 다릅니다');
  const price = num(d.closePrice);
  let diff = num(d.compareToPreviousClosePrice);
  const dir = String((d.compareToPreviousPrice && (d.compareToPreviousPrice.name || d.compareToPreviousPrice.code)) || '');
  if (diff !== null && /FALL|LOWER_LIMIT|^[45]$/.test(dir)) diff = -Math.abs(diff);          // 네이버는 등락 폭을 부호 없이 준다
  else if (diff !== null && /RIS|UPPER_LIMIT|^[12]$/.test(dir)) diff = Math.abs(diff);
  const prev = price !== null && diff !== null ? price - diff : null;
  const over = d.overMarketPriceInfo || null;
  let ext = null;
  if (over && num(over.overPrice)) {
    const kind = String(over.tradingSessionType || '');
    ext = { price: num(over.overPrice), session: /PRE/.test(kind) ? 'pre' : /AFTER/.test(kind) ? 'post' : 'ext',
            open: String(over.overMarketStatus || '') === 'OPEN', chg_pct: num(over.fluctuationsRatio) };
  }
  return { name: d.stockName || d.itemName || null, price, prev, open: num(d.openPrice), high: num(d.highPrice), low: num(d.lowPrice),
           volume: num(d.accumulatedTradingVolume), status: String(d.marketStatus || ''), ext };
}

/** 네이버 1분 시세 응답(prices.py 와 같은 원천) → [[t, close, volume]]. day 가 없으면 들어 있는 가장 최근 거래일 하루. */
export function readNaverMinutes(j, day) {
  const out = [];
  let lastVol = null;
  const rows = Array.isArray(j) ? j : [];
  if (!day) day = rows.reduce((m, x) => { const d = String(x.localDateTime || '').slice(0, 8); return d > m ? d : m; }, '');
  for (const x of rows) {
    const s = String(x.localDateTime || '');
    if (s.slice(0, 8) !== day) continue;
    const t = Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8), +s.slice(8, 10), +s.slice(10, 12)) / 1000 - KST;
    const c = num(x.currentPrice);
    if (c === null) continue;
    const v = num(x.accumulatedTradingVolume) || 0;
    out.push([t, c, lastVol === null ? 0 : Math.max(0, v - lastVol)]);
    lastVol = v;
  }
  return out;
}

/** 한국 호가 단위 — 거래소처럼 시세에 찍힌 값에서 읽는다(표를 외우지 않는다). 값이 적으면 null. */
export function inferTick(values) {
  const vals = values.filter((v) => v !== null).map((v) => Math.round(v));
  if (vals.length < 20) return null;
  for (const t of [1000, 500, 250, 100, 50, 25, 10, 5, 1]) {
    if (vals.filter((v) => v % t === 0).length >= 0.97 * vals.length) return t;
  }
  return 1;
}

function usSession(periods, now) {
  if (!periods) return null;
  const inP = (p) => p && now >= p.start && now < p.end;
  if (inP(periods.regular)) return 'r';
  if (inP(periods.pre)) return 'pre';
  if (inP(periods.post)) return 'post';
  return 'closed';
}

export async function quote(symRaw, fetchFn = fetch, nowSec = Math.floor(Date.now() / 1000)) {
  const sym = String(symRaw || '').trim().toUpperCase();
  if (KR_CODE.test(sym)) {
    const rt = readNaverRealtime(await getJSON(`https://polling.finance.naver.com/api/realtime/domestic/stock/${sym}`, fetchFn));
    let bars = [];
    try {     // 오늘 — 쉬는 날이면 가장 최근 거래일 (최근 7일 안에서)
      const j = await getJSON(`https://api.stock.naver.com/chart/domestic/item/${sym}/minute?startDateTime=${kstDay(nowSec - 7 * 86400)}0800&endDateTime=${kstDay(nowSec)}2000`, fetchFn);
      bars = readNaverMinutes(j);
    } catch (e) { /* 그래프 없이도 현황은 낸다 */ }
    const hm = kstHM(nowSec);
    const session = rt.ext && rt.ext.open ? rt.ext.session : /OPEN/.test(rt.status) && hm >= 900 && hm <= 1530 ? 'r' : 'closed';
    const tick = inferTick(bars.map((b) => b[1]));
    return { symbol: sym, market: 'KR', currency: 'KRW', name: rt.name || sym, price: rt.price, prev: rt.prev, ...chg(rt.price, rt.prev),
             open: rt.open, high: rt.high, low: rt.low, volume: rt.volume, session, ext: rt.ext && { ...rt.ext, ...chg(rt.ext.price, rt.price) },      // 시간외 등락은 정규장 종가 대비 (내 계좌 화면과 같은 기준)
             tick, limits: rt.prev ? { up: Math.floor(rt.prev * 1.3), down: Math.ceil(rt.prev * 0.7) } : null,
             bars: bars.map((b) => [b[0], b[1]]), at: nowSec };
  }
  if (!US_SYM.test(sym)) throw new Error('종목 기호가 올바르지 않습니다');
  const c = readYahooChart(await getJSON(yahooChart(sym, '1d', '1m', true), fetchFn));
  if (c.currency && c.currency !== 'USD') throw new Error('미국 달러로 거래되는 종목이 아닙니다');
  const session = usSession(c.periods, nowSec);
  const reg = c.periods && c.periods.regular ? c.bars.filter((b) => b[0] >= c.periods.regular.start && b[0] < c.periods.regular.end) : c.bars;
  const lastBar = c.bars.length ? c.bars[c.bars.length - 1] : null;
  let ext = null;
  if (lastBar && c.periods && c.periods.regular && (lastBar[0] < c.periods.regular.start || lastBar[0] >= c.periods.regular.end)) {
    ext = { price: lastBar[1], session: lastBar[0] < c.periods.regular.start ? 'pre' : 'post', open: session === 'pre' || session === 'post' };
  }
  return { symbol: sym, market: 'US', currency: 'USD', name: c.name || sym, exchange: c.exchange, kind: c.type === 'ETF' ? 'ETF' : null,
           price: c.price, prev: c.prev, ...chg(c.price, c.prev),
           open: reg.length ? reg[0][3] ?? reg[0][1] : null, high: c.dayHigh, low: c.dayLow, volume: c.volume, session,
           ext: ext && { ...ext, ...chg(ext.price, c.price) }, tick: 0.01, limits: null,      // 시간외 등락은 정규장 종가 대비
           bars: thin2(c.bars, 400), at: nowSec };
}

function thin2(bars, n) {
  if (bars.length <= n) return bars.map((b) => [b[0], b[1]]);
  const step = bars.length / n, out = [];
  for (let i = 0; i < n; i++) { const b = bars[Math.floor(i * step)]; out.push([b[0], b[1]]); }
  const last = bars[bars.length - 1];
  out.push([last[0], last[1]]);
  return out;
}
