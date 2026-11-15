// 에이전트 입구(/api/v1) 시험 — 네트워크 없이 가짜 저장소로 돈다.
// 계좌별 열쇠(Bearer pxk_…)로 자기 계좌만 읽고, 요청은 자기 창구(inbox/{이름표}/)에만 올라가는지.
// 실행: node tests/test_agent_api.mjs
import { handle, newAgentKey, agentFromKey, requestStatus, _resetCaches } from '../site/lib.mjs';

const fails = [];
const check = (label, cond, detail = '') => {
  console.log((cond ? '  통과 ' : '  실패 ') + label + (!cond && detail ? ' — ' + detail : ''));
  if (!cond) fails.push(label);
};

const k1 = await newAgentKey(), k2 = await newAgentKey();
const players = { players: [{ github: 'boss', name: '주인', main: true },
                            { id: 'p1', name: '1호', agent: '선수', api_keys: [{ hash: k1.hash }] },
                            { id: 'bob', name: '밥', email: 'bob@example.com', agent: '친구 에이전트', api_keys: [{ hash: k2.hash }] }] };
const files = {
  'players.json': players,
  'docs/data/accounts/p1.json': { account: '1호', orders: [{ id: 'O0001', client_id: 'c-ord', status: 'pending' },
                                                          { id: 'O0002', client_id: 'x', status: 'canceled', result: { client_id: 'c-can', why: '그만' } }],
                                  refused: [{ client_id: 'c-no', why: '주문 가능 금액이 모자랍니다', ts: 't' }],
                                  watches: [{ id: 'W0001', client_id: 'c-w', status: 'watching' }], forks: [] },
  'docs/data/accounts/bob.json': { account: '밥', orders: [] },
  'docs/data/checks/p1.json': [{ client_id: 'c-chk', ok: false, why: '호가 단위에 맞지 않습니다' }],
  'inbox/p1/c-wait.json': {},
};
let puts = [];
const fetchFn = async (url, init = {}) => {
  const m = /^https:\/\/api\.github\.com\/repos\/owner\/data\/(.*)$/.exec(url);
  if (!m || init.headers.authorization !== 'Bearer tok') return new Response('no', { status: 401 });
  if ((init.method || 'GET') === 'GET' && m[1].startsWith('contents/')) {
    const f = files[decodeURIComponent(m[1].slice(9).split('?')[0])];
    return f !== undefined ? Response.json(f) : new Response('없음', { status: 404 });
  }
  if (init.method === 'PUT' && m[1].startsWith('contents/')) {
    const path = m[1].slice(9);
    if (files[path] !== undefined) return new Response('exists', { status: 422 });
    puts.push({ path, body: JSON.parse(Buffer.from(JSON.parse(init.body).content, 'base64').toString('utf8')) });
    return Response.json({ ok: true }, { status: 201 });
  }
  return new Response('?', { status: 500 });
};
const env = { GITHUB_REPO: 'owner/data', GITHUB_TOKEN: 'tok', AUTH_SVC: { fetch: async () => Response.json({ authenticated: false }, { status: 401 }) } };
const site = 'https://exchange.sharktalk.co.kr';
async function call(path, key, { method = 'GET', body, headers = {} } = {}) {
  const h = { ...headers };
  if (key) h.Authorization = `Bearer ${key}`;
  if (body !== undefined) h['content-type'] = h['content-type'] || 'application/json';
  puts = [];
  const res = await handle(new Request(site + path, { method, headers: h, body: body === undefined ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)) }),
                           env, async () => new Response('화면'), fetchFn);
  const text = await res.text(); let data; try { data = JSON.parse(text); } catch (e) { data = text; }
  return { status: res.status, data };
}
_resetCaches();

console.log('열쇠');
check('열쇠 모양 pxk_ + 40자, 지문은 sha256', /^pxk_[A-Za-z0-9]{40}$/.test(k1.key) && /^[0-9a-f]{64}$/.test(k1.hash) && k1.key !== k2.key);
check('열쇠가 없거나 틀리면 401', (await call('/api/v1/account')).status === 401 && (await call('/api/v1/account', 'pxk_' + 'A'.repeat(40))).status === 401
      && (await call('/api/v1/account', 'not-a-key')).status === 401);
check('sharktalk 로그인 쿠키로는 열리지 않는다', (await call('/api/v1/account', null, { headers: { Cookie: 'st_session=boss' } })).status === 401);
const who = await agentFromKey(new Request(site, { headers: { Authorization: `Bearer ${k2.key}` } }), players);
check('열쇠 → 계좌', who && who.id === 'bob');

console.log('내 계좌만');
let r = await call('/api/v1/account', k1.key);
check('자기 계좌 자료', r.status === 200 && r.data.account === '1호', JSON.stringify(r.data));
r = await call('/api/v1/account', k2.key);
check('다른 열쇠는 다른 계좌', r.status === 200 && r.data.account === '밥');
check('남의 자료·관리자 자료로 가는 길은 없다', (await call('/api/v1/accounts/p1', k2.key)).status === 404 && (await call('/data/league.json', k2.key)).status === 401
      && (await call('/api/admin', k2.key, { method: 'POST', body: { action: 'add_player', id: 'x' } })).status === 401);

console.log('요청 보내기');
r = await call('/api/v1/requests', k2.key, { method: 'POST', body: { symbol: 'MU', side: 'buy', qty: 3, ref: 'D1', account: 'p1', hack: 1, client_id: 'bob-1' } });
check('자기 창구(inbox/bob/)에만 올라가고 202 + client_id', r.status === 202 && r.data.client_id === 'bob-1' && puts.length === 1
      && puts[0].path === 'inbox/bob/bob-1.json' && puts[0].body.symbol === 'MU' && puts[0].body.qty === 3 && !('account' in puts[0].body) && !('hack' in puts[0].body)
      && puts[0].body.requested_at, JSON.stringify(puts));
r = await call('/api/v1/requests', k1.key, { method: 'POST', body: { symbol: '005930', side: 'buy', qty: 1, dry_run: true } });
check('검사만(dry_run)도 창구로, client_id 를 만들어 준다', r.status === 202 && /^api-/.test(r.data.client_id) && puts[0].body.dry_run === true && puts[0].path.startsWith('inbox/p1/'));
r = await call('/api/v1/requests', k1.key, { method: 'POST', body: { action: 'fork', ref: 'D3', arguments: { 그대로: '가'.repeat(7000), 줄이기: '나' } } });
check('분기 요청의 논거 글은 실려 가되 잘린다', r.status === 202 && puts[0].body.arguments.그대로.length === 6000 && puts[0].body.arguments.줄이기 === '나');
check('같은 client_id 가 아직 창구에 있으면 409', (await call('/api/v1/requests', k1.key, { method: 'POST', body: { symbol: 'MU', side: 'buy', qty: 1, client_id: 'c-wait' } })).status === 409);
check('이상한 client_id·JSON 아님·너무 긴 요청은 400', (await call('/api/v1/requests', k1.key, { method: 'POST', body: { client_id: '../../x' } })).status === 400
      && (await call('/api/v1/requests', k1.key, { method: 'POST', body: 'x', headers: { 'content-type': 'text/plain' } })).status === 400
      && (await call('/api/v1/requests', k1.key, { method: 'POST', body: { ref: 'x'.repeat(50000) } })).status === 400);

console.log('요청 결과');
const st = async (cid) => (await call(`/api/v1/requests/${cid}`, k1.key)).data;
check('접수된 주문', (await st('c-ord')).status === 'accepted' && (await st('c-ord')).order.id === 'O0001');
check('취소 접수', (await st('c-can')).action === 'cancel' && (await st('c-can')).order.id === 'O0002');
check('받지 않음 + 사유', (await st('c-no')).status === 'refused' && /모자랍니다/.test((await st('c-no')).why));
check('지켜보기', (await st('c-w')).action === 'watch');
check('검사만 한 결과', (await st('c-chk')).status === 'checked' && (await st('c-chk')).result.why.includes('호가'));
check('아직 창구에 있음 / 모름', (await st('c-wait')).status === 'queued' && (await st('nothing')).status === 'unknown');
check('남의 요청 번호로는 남의 결과를 못 본다', (await call('/api/v1/requests/c-ord', k2.key)).data.status === 'unknown');
check('requestStatus 직접', requestStatus('a', { orders: [{ client_id: 'a', id: 'O1' }] }, [], false).status === 'accepted');

console.log('관리자: 열쇠 발급');
const stEnv = { ...env, ADMIN_EMAILS: 'boss@example.com',
  AUTH_SVC: { fetch: async (req) => req.headers.get('cookie') === 'st_session=boss'
    ? Response.json({ authenticated: true, user: { email: 'boss@example.com' } }) : Response.json({ authenticated: false }, { status: 401 }) } };
puts = [];
const res = await handle(new Request(site + '/api/admin', { method: 'POST', headers: { Cookie: 'st_session=boss', Origin: site, 'content-type': 'application/json' },
  body: JSON.stringify({ action: 'issue_key', id: 'bob' }) }), stEnv, async () => new Response(''), fetchFn);
const j = await res.json();
const adm = puts.find((x) => x.path.startsWith('admin/'));
check('주인이 열쇠를 만들면 평문은 한 번만 돌려주고, 거래소에는 지문만 간다', res.status === 200 && /^pxk_/.test(j.key) && adm && adm.body.action === 'set_key'
      && adm.body.id === 'bob' && /^[0-9a-f]{64}$/.test(adm.body.hash) && !JSON.stringify(adm.body).includes(j.key), JSON.stringify({ j, adm }));

console.log('요청 횟수 막이');
let last;
for (let i = 0; i < 61; i++) last = await call('/api/v1/account', k2.key);
check('1분에 60번을 넘으면 429', last.status === 429);

console.log(`\n${fails.length ? '실패 ' + fails.length + '건' : '전부 통과'}`);
process.exit(fails.length ? 1 : 0);
