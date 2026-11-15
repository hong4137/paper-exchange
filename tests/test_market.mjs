// 주문 페이지 시장 정보 시험 — 네트워크 없이 가짜 원천 응답으로 돈다. 실제 원천은 tests/probe_market.mjs 가 본다.
// 실행: node tests/test_market.mjs
import * as M from '../site/market.mjs';
import { handle, _resetCaches } from '../site/lib.mjs';

const fails = [];
const check = (label, cond, detail = '') => {
  console.log((cond ? '  통과 ' : '  실패 ') + label + (!cond && detail ? ' — ' + detail : ''));
  if (!cond) fails.push(label);
};

// 2026-11-16(월) 한국 10:00 = 01:00Z
const NOW = Date.UTC(2026, 10, 16, 1, 0) / 1000;
const yChart = (sym, { price, prev, closes, start, step = 60, periods, currency = 'USD', name }) => ({
  chart: { result: [{ meta: { symbol: sym, regularMarketPrice: price, chartPreviousClose: prev, previousClose: prev, currency, longName: name || sym,
                              regularMarketTime: start + step * (closes.length - 1), currentTradingPeriod: periods },
                      timestamp: closes.map((_, i) => start + step * i),
                      indicators: { quote: [{ close: closes, open: closes, high: closes, low: closes, volume: closes.map(() => 100) }] } }] } });
const US_REG = { start: Date.UTC(2026, 10, 16, 14, 30) / 1000, end: Date.UTC(2026, 10, 16, 21, 0) / 1000 };
const US_PER = { pre: { start: US_REG.start - 5.5 * 3600, end: US_REG.start }, regular: US_REG, post: { start: US_REG.end, end: US_REG.end + 4 * 3600 } };

const routes = {};
const hits = [];
const fetchFn = async (url) => {
  hits.push(url);
  for (const [k, v] of Object.entries(routes)) if (url.includes(k)) return typeof v === 'function' ? v(url) : Response.json(v);
  return new Response('없음', { status: 404 });
};

console.log('시장 현황');
for (const o of M.OVERVIEW) routes[`/chart/${encodeURIComponent(o.y)}?`] = yChart(o.y, { price: 110, prev: 100, closes: [100, 105, 110], start: NOW - 600, step: 300 });
routes[`/chart/${encodeURIComponent('^TNX')}?`] = yChart('^TNX', { price: 42.5, prev: 42.0, closes: [42.0, 42.5], start: NOW - 600, step: 300 });
delete routes[`/chart/${encodeURIComponent('^HSI')}?`];
let ov = await M.overview(fetchFn);
const by = Object.fromEntries(ov.items.map((x) => [x.key, x]));
check('열다섯 가지가 네 묶음으로 나온다', ov.items.length === 15 && new Set(ov.items.map((x) => x.group)).size === 4);
check('등락과 등락률: 100 → 110 = +10, +10%', by.kospi.price === 110 && by.kospi.chg === 10 && by.kospi.chg_pct === 10 && by.kospi.spark.length === 3, JSON.stringify(by.kospi));
check('금리는 %로, 옛 표기(×10)면 나눠서, 바뀐 폭은 %p 로', by.tnx.price === 4.25 && by.tnx.chg === 0.05 && by.tnx.chg_pct === null && by.tnx.rate, JSON.stringify(by.tnx));
check('하나를 못 받아도 나머지는 나온다', by.hsi.error && by.spx.price === 110);
const n = hits.length;
await M.overview(fetchFn);
check('30초 안에 다시 보면 받은 것은 다시 묻지 않는다 (못 받은 것만 다시 묻는다)', hits.length === n + 1 && hits.at(-1).includes('HSI'), String(hits.length - n));

console.log('종목 현황 — 한국');
M._resetMarket();
routes['polling.finance.naver.com/api/realtime/domestic/stock/005930'] = { datas: [{ stockName: '삼성전자', closePrice: '209,000', compareToPreviousClosePrice: '-1,000',
  fluctuationsRatio: '-0.48', openPrice: '210,000', highPrice: '211,000', lowPrice: '208,500', accumulatedTradingVolume: '1,234,567', marketStatus: 'OPEN' }] };
const kmin = [];
for (let i = 0; i < 40; i++) {
  const t = new Date((NOW - 3600 + i * 60 + 9 * 3600) * 1000).toISOString();
  kmin.push({ localDateTime: t.slice(0, 4) + t.slice(5, 7) + t.slice(8, 10) + t.slice(11, 13) + t.slice(14, 16) + '00', currentPrice: 209000 + (i % 4) * 500, accumulatedTradingVolume: 1000 * (i + 1) });
}
kmin.push({ localDateTime: '202611130930' + '00', currentPrice: 1, accumulatedTradingVolume: 1 });   // 다른 날 — 빼야 한다
routes['api.stock.naver.com/chart/domestic/item/005930/minute'] = kmin;
let q = await M.quote('005930', fetchFn, NOW);
check('현재가·전일 종가·등락', q.name === '삼성전자' && q.price === 209000 && q.prev === 210000 && q.chg === -1000 && q.chg_pct === -0.48, JSON.stringify(q).slice(0, 200));
check('정규장 시간이면 "정규장"', q.session === 'r');
check('호가 단위를 그날 시세에서 읽는다 (500원)', q.tick === 500, String(q.tick));
check('상·하한가 = 전일 종가 ±30%', q.limits.up === 273000 && q.limits.down === 147000, JSON.stringify(q.limits));
check('그래프는 오늘 것만', q.bars.length === 40 && q.bars.every((b) => b[1] > 1000));
M._resetMarket();
routes['polling.finance.naver.com/api/realtime/domestic/stock/005930'] = { datas: [{ stockName: '삼성전자', closePrice: '209,000', compareToPreviousClosePrice: '-1,000',
  marketStatus: 'CLOSE', overMarketPriceInfo: { tradingSessionType: 'AFTER_MARKET', overMarketStatus: 'OPEN', overPrice: '207,500', fluctuationsRatio: '-1.19' } }] };
q = await M.quote('005930', fetchFn, NOW + 8 * 3600);
check('장후(넥스트레이드)가 열려 있으면 "장후"와 그 가격', q.session === 'post' && q.ext.price === 207500 && q.ext.chg === -2500, JSON.stringify(q.ext));

console.log('종목 현황 — 미국');
M._resetMarket();
const usNow = US_REG.start + 3600;
routes[`/chart/MU?`] = yChart('MU', { price: 101, prev: 100, closes: [99, 100, 101], start: US_REG.start - 120, periods: US_PER, name: 'Micron Technology' });
q = await M.quote('mu', fetchFn, usNow);
check('미국 종목: 정규장, 등락', q.symbol === 'MU' && q.market === 'US' && q.session === 'r' && q.chg === 1 && q.chg_pct === 1 && q.tick === 0.01, JSON.stringify(q).slice(0, 200));
M._resetMarket();
routes[`/chart/MU?`] = yChart('MU', { price: 101, prev: 100, closes: [100, 101, 103], start: US_REG.end - 60, periods: US_PER });
q = await M.quote('MU', fetchFn, US_REG.end + 1800);
check('장후 1분 시세가 있으면 장후 가격을 따로', q.session === 'post' && q.ext && q.ext.price === 103 && q.ext.session === 'post' && q.ext.chg_pct === 3, JSON.stringify(q.ext));
M._resetMarket();
routes[`/chart/SONY?`] = yChart('SONY', { price: 3000, prev: 2900, closes: [3000], start: NOW, currency: 'JPY' });
let err = null; try { await M.quote('SONY', fetchFn, NOW); } catch (e) { err = e.message; }
check('달러가 아닌 종목은 받지 않는다', /달러/.test(err || ''), err);
err = null; try { await M.quote('../etc', fetchFn, NOW); } catch (e) { err = e.message; }
check('이상한 기호는 원천에 묻지도 않는다', /올바르지/.test(err || '') && !hits.some((h) => h.includes('etc')), err);

console.log('종목 검색');
M._resetMarket();
routes['ac.stock.naver.com/ac'] = { query: '삼성', items: [{ code: '005930', name: '삼성전자', typeCode: 'KOSPI', typeName: '코스피', nationCode: 'KOR', category: 'stock' },
  { code: '005935', name: '삼성전자우', typeName: '코스피', nationCode: 'KOR' }, { code: 'SSNLF', reutersCode: 'SSNLF', name: '삼성(미국)', nationCode: 'USA' }] };
routes['/v1/finance/search'] = { quotes: [{ symbol: 'MU', shortname: 'Micron', longname: 'Micron Technology, Inc.', exchange: 'NMS', exchDisp: 'NASDAQ', quoteType: 'EQUITY' },
  { symbol: 'MU.MX', quoteType: 'EQUITY', exchange: 'MEX' }, { symbol: '005930.KS', shortname: 'Samsung Elec', quoteType: 'EQUITY', exchange: 'KSC' },
  { symbol: '^GSPC', quoteType: 'INDEX' }, { symbol: 'BTC-USD', quoteType: 'CRYPTOCURRENCY' }] };
let s = await M.search('삼성', fetchFn);
check('한글 이름으로 한국 종목을 찾는다', s.items[0].symbol === '005930' && s.items[0].name === '삼성전자' && s.items[0].market === 'KR' && s.items.some((x) => x.symbol === '005935'), JSON.stringify(s.items));
check('한글로 찾을 때는 야후에 묻지 않는다', !hits.some((h) => h.includes('/v1/finance/search?q=%EC')));
s = await M.search('micron', fetchFn);
check('영문 이름으로 미국 종목을 찾고, 미국 밖 거래소·지수·코인은 뺀다', s.items.some((x) => x.symbol === 'MU' && x.market === 'US' && x.name.startsWith('Micron'))
      && !s.items.some((x) => /MU\.MX|\^GSPC|BTC/.test(x.symbol)), JSON.stringify(s.items));
check('같은 종목은 한 번만 (네이버·야후 양쪽에서 나온 005930)', s.items.filter((x) => x.symbol === '005930').length <= 1);
s = await M.search('069500', fetchFn);
check('여섯 자리 번호는 그대로 한국 종목으로', s.items[0].symbol === '069500' && s.items[0].market === 'KR');
check('빈 검색은 빈 목록', (await M.search('  ', fetchFn)).items.length === 0);

console.log('문지기 뒤에서');
_resetCaches(); M._resetMarket();
const cfg = { players: [{ github: 'boss', name: '주인', main: true }, { id: 'alice', name: '앨리스', email: 'alice@example.com' }] };
const env = { GITHUB_REPO: 'o/r', GITHUB_TOKEN: 't', ADMIN_EMAILS: 'boss@example.com',
  AUTH_SVC: { fetch: async (req) => /st_session=alice/.test(req.headers.get('cookie') || '')
    ? Response.json({ authenticated: true, user: { email: 'alice@example.com' } }) : Response.json({ authenticated: false }, { status: 401 }) } };
const gw = async (url, init) => url.includes('api.github.com') ? Response.json(cfg) : fetchFn(url, init);
const call = async (path, cookie, method = 'GET') => {
  const r = await handle(new Request('https://ex.test' + path, { method, headers: cookie ? { Cookie: cookie } : {} }), env, async () => new Response('화면'), gw);
  return { status: r.status, data: await r.json().catch(() => null) };
};
check('로그인하지 않으면 시장 정보도 내주지 않는다', (await call('/api/market')).status === 401 && (await call('/api/quote?symbol=MU')).status === 401);
let r = await call('/api/quote?symbol=005930', 'st_session=alice');
check('로그인한 참가자는 종목 현황을 본다', r.status === 200 && r.data.price === 209000, JSON.stringify(r.data).slice(0, 120));
r = await call('/api/search?q=%EC%82%BC%EC%84%B1', 'st_session=alice');
check('로그인한 참가자는 검색한다', r.status === 200 && r.data.items.length >= 2);
check('시장 정보는 읽기만 (GET 말고는 받지 않는다)', (await call('/api/market', 'st_session=alice', 'POST')).status === 405);
r = await call('/api/quote?symbol=ZZZZ', 'st_session=alice');
check('원천이 답하지 않으면 사람 말로 알린다', r.status === 502 && /시세를 받지 못했습니다/.test(r.data.error), JSON.stringify(r.data));

console.log(`\n${fails.length ? '실패 ' + fails.length + '건' : '전부 통과'}`);
process.exit(fails.length ? 1 : 0);
