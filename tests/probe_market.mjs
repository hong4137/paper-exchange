// 주문 페이지의 시세 원천이 실제로 어떤 모양으로 답하는지 찍는다 (GitHub 확인 실행에서 돈다). 아무것도 저장하지 않는다.
// 실행: node tests/probe_market.mjs   — 원천이 하나라도 막히거나 모양이 다르면 종료 코드 1
import * as M from '../site/market.mjs';

let fails = 0;
const UA = { 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36', accept: 'application/json' };
async function probe(label, fn) {
  try { console.log(`  열림  ${label}: ${await fn()}`); }
  catch (e) { fails++; console.log(`  막힘  ${label}: ${String(e && e.message || e).slice(0, 200)}`); }
}
const shape = (x, depth = 0) => {
  if (Array.isArray(x)) return `[${x.length}× ${x.length ? shape(x[0], depth + 1) : ''}]`;
  if (x && typeof x === 'object') return depth > 2 ? '{…}' : `{${Object.keys(x).slice(0, 25).map((k) => `${k}:${shape(x[k], depth + 1)}`).join(', ')}}`;
  return typeof x;
};
const raw = async (url) => { const r = await fetch(url, { headers: UA }); if (!r.ok) throw new Error(`응답 ${r.status}`); return r.json(); };

console.log('원천 응답 모양 (해석 함수를 맞출 때 본다)');
await probe('네이버 자동완성 삼성', async () => shape(await raw('https://ac.stock.naver.com/ac?q=%EC%82%BC%EC%84%B1&target=stock')).slice(0, 700));
await probe('네이버 자동완성 마이크론', async () => JSON.stringify(await raw('https://ac.stock.naver.com/ac?q=%EB%A7%88%EC%9D%B4%ED%81%AC%EB%A1%A0&target=stock')).slice(0, 700));
await probe('네이버 실시간 005930', async () => JSON.stringify(await raw('https://polling.finance.naver.com/api/realtime/domestic/stock/005930')).slice(0, 900));
await probe('야후 검색 micron', async () => shape(await raw('https://query1.finance.yahoo.com/v1/finance/search?q=micron&quotesCount=5&newsCount=0&listsCount=0')).slice(0, 500));

console.log('해석한 결과');
await probe('시장 현황', async () => {
  const o = await M.overview();
  const bad = o.items.filter((x) => x.error || x.price === null);
  if (bad.length) throw new Error('못 받은 것: ' + bad.map((x) => x.label).join(', ') + ' / 받은 것: ' + o.items.filter((x) => !x.error).map((x) => `${x.label} ${x.price} (${x.chg_pct ?? x.chg})`).join(', '));
  return o.items.map((x) => `${x.label} ${x.price}${x.unit === '%' ? '%' : ''} (${x.rate ? x.chg + '%p' : x.chg_pct + '%'}, 점 ${x.spark.length})`).join(' · ');
});
for (const q of ['삼성', '마이크론', 'micron', 'nvda', '069500']) {
  await probe(`검색 "${q}"`, async () => {
    const r = await M.search(q);
    if (!r.items.length) throw new Error('결과 없음');
    return r.items.slice(0, 6).map((x) => `${x.market} ${x.symbol} ${x.name}${x.direct ? '(직접)' : ''}`).join(' · ');
  });
}
for (const sym of ['005930', '069500', '247540', 'MU', 'QQQ']) {
  await probe(`종목 ${sym}`, async () => {
    const q = await M.quote(sym);
    if (!q.price || !q.prev) throw new Error('가격 없음: ' + JSON.stringify(q).slice(0, 300));
    return `${q.name} ${q.price} (전일 ${q.prev}, ${q.chg_pct}%) · ${q.session} · 시간외 ${q.ext ? q.ext.session + ' ' + q.ext.price : '없음'} · 호가 ${q.tick} · 상·하한 ${q.limits ? q.limits.down + '~' + q.limits.up : '-'} · 그래프 점 ${q.bars.length}`;
  });
}
console.log(fails ? `\n막힌 곳 ${fails}군데` : '\n전부 열림');
process.exit(fails ? 1 : 0);
