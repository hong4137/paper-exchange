// 거래소 화면의 문지기 시험 — 네트워크 없이, 가짜 저장소로 돈다. 로그인은 거래소 자체 열쇠 세션(px_session)이다.
// 실행: node tests/test_site.mjs
import { handle, canRead, makeSession, newAgentKey, _resetCaches } from '../site/lib.mjs';

const fails = [];
const check = (label, cond, detail = '') => {
  console.log((cond ? '  통과 ' : '  실패 ') + label + (!cond && detail ? ' — ' + detail : ''));
  if (!cond) fails.push(label);
};

// 계좌마다 열쇠 하나 (명단에는 지문만)
const K = { boss: await newAgentKey(), alice: await newAgentKey(), bob: await newAgentKey(), evil: await newAgentKey() };
const env = { GITHUB_REPO: 'owner/repo', GITHUB_TOKEN: 'tok' };
const config = { players: [{ github: 'boss', name: '주인', main: true, api_keys: [{ hash: K.boss.hash }] },
                           { github: 'Alice', name: '앨리스', api_keys: [{ hash: K.alice.hash }] },
                           { id: 'bob', name: '밥', api_keys: [{ hash: K.bob.hash }] },
                           { github: '../evil', name: '나쁜 이름', api_keys: [{ hash: K.evil.hash }] }] };
const files = { 'players.json': config, 'docs/data/accounts/alice.json': { account: '앨리스' }, 'docs/data/accounts/boss.json': { account: '주인' },
                'docs/data/league.json': { players: [] }, 'docs/data/state.json': { account: '주인' } };
let calls = [];
const fetchFn = async (url, init = {}) => {
  calls.push({ url, init });
  const m = /^https:\/\/api\.github\.com\/repos\/owner\/repo\/(.*)$/.exec(url);
  if (!m || init.headers.authorization !== 'Bearer tok') return new Response('no', { status: 401 });
  if ((init.method || 'GET') === 'GET' && m[1].startsWith('contents/')) {
    const f = files[decodeURIComponent(m[1].slice(9).split('?')[0])];
    return f ? Response.json(f) : new Response('없음', { status: 404 });
  }
  if (init.method === 'PUT' && /^contents\/(inbox|admin)\//.test(m[1])) return Response.json({ ok: true }, { status: 201 });
  return new Response('?', { status: 500 });
};
const site = 'https://exchange.example';
const sess = {};
for (const id of ['boss', 'alice', 'bob']) sess[id] = 'px_session=' + await makeSession(env, id, K[id].hash);
sess.stranger = 'px_session=' + await makeSession(env, 'stranger', 'f'.repeat(64));
sess['../evil'] = 'px_session=' + await makeSession(env, '../evil', K.evil.hash);
async function call(path, who, { method = 'GET', body, headers = {} } = {}) {
  const h = { ...headers };
  if (who) h.Cookie = sess[who];
  if (body !== undefined) { h['content-type'] = h['content-type'] || 'application/json'; h.Origin = h.Origin || site; }
  calls = [];
  const res = await handle(new Request(site + path, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) }),
                           env, async () => new Response('화면', { status: 200 }), fetchFn);
  let data = null;
  const text = await res.text();
  try { data = JSON.parse(text); } catch (e) { data = text; }
  return { status: res.status, data };
}

console.log('로그인 확인');
check('세션이 없으면 화면도 자료도 내주지 않는다', (await call('/')).status === 401 && (await call('/data/league.json')).status === 401);
check('sharktalk 쿠키는 아무 소용 없다', (await call('/api/me', null, { headers: { Cookie: 'st_session=boss' } })).status === 401);
check('다른 서명 열쇠로 만든 세션은 받지 않는다', (await handle(new Request(site + '/api/me', { headers: { Cookie: 'px_session=' + await makeSession({ GITHUB_TOKEN: 'other' }, 'boss', K.boss.hash) } }),
      env, async () => new Response(''), fetchFn)).status === 401);
check('기한이 지난 세션은 받지 않는다', (await handle(new Request(site + '/api/me', { headers: { Cookie: 'px_session=' + await makeSession(env, 'boss', K.boss.hash, Date.now() - 31 * 86400000) } }),
      env, async () => new Response(''), fetchFn)).status === 401);

console.log('누구인지');
let r = await call('/api/me', 'boss');
check('관리자: 주인 계좌의 주인으로 본다', r.status === 200 && r.data.admin === true && r.data.id === 'boss', JSON.stringify(r.data));
r = await call('/api/me', 'alice');
check('참가자: 열쇠의 계좌 (GitHub 계정 대소문자 무시)', r.data.id === 'alice' && r.data.admin === false && r.data.name === '앨리스', JSON.stringify(r.data));
check('GitHub 계정 없이 이름표(id)만 있는 참가자도 된다', (await call('/api/me', 'bob')).data.id === 'bob');
r = await call('/', 'stranger');
check('명단에 없는(또는 열쇠가 끊긴) 세션은 들이지 않는다', r.status === 401 && (await call('/data/accounts/alice.json', 'stranger')).status === 401);
check('파일 이름이 될 수 없는 계정은 계좌로 치지 않는다', (await call('/api/me', '../evil')).status === 401);

console.log('무엇을 볼 수 있나');
check('참가자는 자기 계좌 자료를 본다', (r = await call('/data/accounts/alice.json', 'alice')).status === 200 && r.data.account === '앨리스');
check('참가자는 남의 계좌 자료를 못 본다', (await call('/data/accounts/boss.json', 'alice')).status === 403 && (await call('/data/accounts/bob.json', 'alice')).status === 403);
check('참가자는 전체 수익률·주인 계좌·관리자 화면을 못 본다', (await call('/data/league.json', 'alice')).status === 403
      && (await call('/data/state.json', 'alice')).status === 403 && (await call('/admin.html', 'alice')).status === 403);
check('관리자는 전부 본다', (await call('/data/league.json', 'boss')).status === 200 && (await call('/data/accounts/alice.json', 'boss')).status === 200
      && (await call('/admin.html', 'boss')).data === '화면');
check('정해진 자료 말고는 저장소의 아무것도 내주지 않는다 (설정·장부·경로 장난)', (await call('/data/../config.json', 'boss')).data === '화면'      // 주소가 /config.json 으로 정리되어 화면 파일 쪽으로 간다 (저장소에서 읽지 않는다)
      && (await call('/data/accounts/..%2F..%2Fconfig.json', 'boss')).status === 403 && !canRead('/data/roster.json', { admin: true, id: 'boss', main: true }));
check('아직 자료가 없는 계좌는 없다고 답한다', (await call('/data/accounts/bob.json', 'bob')).status === 404);
check('거래소 화면은 명단에 있는 누구에게나 내준다', (await call('/', 'alice')).data === '화면');

console.log('주문');
r = await call('/api/order', 'alice', { method: 'POST', body: { account: 'boss', symbol: 'MU', side: 'buy', qty: 3, hack: { a: 1 }, client_id: 'x' } });
const put = calls.find((c) => c.init.method === 'PUT');
const sent = put ? JSON.parse(Buffer.from(JSON.parse(put.init.body).content, 'base64').toString('utf8')) : {};
check('주문은 로그인한 사람의 창구 폴더에 올라간다 (요청 안의 계좌는 보지 않는다)', r.status === 200 && put && put.url.includes('/contents/inbox/alice/web-')
      && sent.symbol === 'MU' && sent.qty === 3 && !('account' in sent) && !('hack' in sent) && sent.client_id === r.data.client_id && sent.client_id !== 'x', JSON.stringify(sent));
check('다른 사이트에서 몰래 보낸 주문은 받지 않는다', (await call('/api/order', 'alice', { method: 'POST', body: { symbol: 'MU' }, headers: { Origin: 'https://evil.example' } })).status === 403
      && !calls.some((c) => c.init.method === 'PUT'));
check('정해진 모양이 아닌 주문은 받지 않는다', (await call('/api/order', 'alice', { method: 'POST', body: [1, 2] })).status === 400
      && (await call('/api/order', 'alice', { method: 'POST', body: { symbol: 'MU' }, headers: { 'content-type': 'text/plain' } })).status === 400);

console.log('관리');
r = await call('/api/admin', 'alice', { method: 'POST', body: { action: 'add_player', id: 'carol' } });
check('참가자는 관리 명령을 낼 수 없다', r.status === 403 && !calls.some((c) => c.init.method === 'PUT'));
r = await call('/api/admin', 'boss', { method: 'POST', body: { action: 'add_player', id: 'carol', email: 'carol@example.com', name: '캐럴', extra: 'x' } });
const aput = calls.find((c) => c.init.method === 'PUT');
const adminReq = aput ? JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(JSON.parse(aput.init.body).content), (c) => c.charCodeAt(0)))) : {};
check('관리자의 명령은 자료 저장소의 admin/ 에 요청 파일로 넘어간다 (이슈를 열지 않는다)', r.status === 200 && /\/contents\/admin\/[0-9a-f]+-[0-9a-f]{8}\.json$/.test(aput.url)
      && adminReq.action === 'add_player' && adminReq.email === 'carol@example.com' && !('extra' in adminReq) && adminReq.requested_at
      && !calls.some((c) => c.init.method === 'POST'), JSON.stringify(adminReq));
check('관리 요청의 결과는 관리자만 본다', canRead('/data/admin_log.json', { admin: true }) && !canRead('/data/admin_log.json', { admin: false, id: 'alice' }));
check('모르는 관리 명령은 넘기지 않는다', (await call('/api/admin', 'boss', { method: 'POST', body: { action: 'drop_all' } })).status === 400);
r = await call('/api/admin', 'boss', { method: 'POST', body: { action: 'add_player', id: 'dan', login: 'dan-st' } });
check('관리 명령의 칸은 정해진 것만 넘어간다', r.status === 200 && atob(JSON.parse(calls.find((c) => c.init.method === 'PUT').init.body).content).includes('"login":"dan-st"'));


console.log(`\n${fails.length ? '실패 ' + fails.length + '건' : '전부 통과'}`);
process.exit(fails.length ? 1 : 0);
