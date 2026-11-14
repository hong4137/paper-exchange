// 로그인 있는 화면의 문지기 시험 — 네트워크 없이, 가짜 열쇠와 가짜 저장소로 돈다.
// 실행: node tests/test_site.mjs
import { handle, canRead, whoami, identityFromMe, _resetCaches } from '../site/lib.mjs';

const fails = [];
const check = (label, cond, detail = '') => {
  console.log((cond ? '  통과 ' : '  실패 ') + label + (!cond && detail ? ' — ' + detail : ''));
  if (!cond) fails.push(label);
};
const b64u = (bytes) => Buffer.from(bytes).toString('base64url');

// 가짜 로그인 열쇠 (Cloudflare Access 가 서명하는 것을 흉내 낸다)
const pair = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048,
  publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const other = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048,
  publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const jwk = { ...(await crypto.subtle.exportKey('jwk', pair.publicKey)), kid: 'k1' };
const env = { ACCESS_TEAM: 'team.cloudflareaccess.com', ACCESS_AUD: 'aud-123', GITHUB_REPO: 'owner/repo', GITHUB_TOKEN: 'tok',
              ADMIN_EMAILS: 'Boss@Example.com' };
async function token(email, over = {}, key = pair.privateKey) {
  const h = b64u(JSON.stringify({ alg: 'RS256', kid: 'k1', ...(over.header || {}) }));
  const p = b64u(JSON.stringify({ aud: ['aud-123'], iss: 'https://team.cloudflareaccess.com', email,
                                  exp: Math.floor(Date.now() / 1000) + 600, ...(over.claims || {}) }));
  const sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key, new TextEncoder().encode(`${h}.${p}`));
  return `${h}.${p}.${b64u(new Uint8Array(sig))}`;
}

// 가짜 저장소
const config = { players: [{ github: 'boss', name: '주인', main: true },
                           { github: 'Alice', name: '앨리스', email: 'alice@example.com' },
                           { id: 'bob', name: '밥', email: 'BOB@example.com' },
                           { github: '../evil', name: '나쁜 이름', email: 'evil@example.com' }] };
const files = { 'config.json': config, 'docs/data/accounts/alice.json': { account: '앨리스' }, 'docs/data/accounts/boss.json': { account: '주인' },
                'docs/data/league.json': { players: [] }, 'docs/data/state.json': { account: '주인' } };
let calls = [];
const fetchFn = async (url, init = {}) => {
  calls.push({ url, init });
  if (url === 'https://team.cloudflareaccess.com/cdn-cgi/access/certs') return Response.json({ keys: [jwk] });
  const m = /^https:\/\/api\.github\.com\/repos\/owner\/repo\/(.*)$/.exec(url);
  if (!m || init.headers.authorization !== 'Bearer tok') return new Response('no', { status: 401 });
  if ((init.method || 'GET') === 'GET' && m[1].startsWith('contents/')) {
    const f = files[decodeURIComponent(m[1].slice(9).split('?')[0])];
    return f ? Response.json(f) : new Response('없음', { status: 404 });
  }
  if (init.method === 'PUT' && m[1].startsWith('contents/inbox/')) return Response.json({ ok: true }, { status: 201 });
  if (init.method === 'POST' && m[1] === 'issues') return Response.json({ number: 7 }, { status: 201 });
  return new Response('?', { status: 500 });
};
const site = 'https://ex.pages.dev';
async function call(path, email, { method = 'GET', body, headers = {}, tok } = {}) {
  const h = { ...headers };
  if (email || tok) h['Cf-Access-Jwt-Assertion'] = tok || await token(email);
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
check('토큰이 없으면 화면도 자료도 내주지 않는다', (await call('/')).status === 401 && (await call('/data/league.json')).status === 401);
check('다른 열쇠로 서명한 토큰은 받지 않는다', (await call('/api/me', null, { tok: await token('boss@example.com', {}, other.privateKey) })).status === 401);
check('기한이 지난 토큰은 받지 않는다', (await call('/api/me', null, { tok: await token('boss@example.com', { claims: { exp: 1000 } }) })).status === 401);
check('다른 애플리케이션용 토큰은 받지 않는다', (await call('/api/me', null, { tok: await token('boss@example.com', { claims: { aud: ['other'] } }) })).status === 401);
check('발급처가 다른 토큰은 받지 않는다', (await call('/api/me', null, { tok: await token('boss@example.com', { claims: { iss: 'https://evil.cloudflareaccess.com' } }) })).status === 401);
check('서명 방식을 없앤 토큰은 받지 않는다', (await call('/api/me', null, { tok: await token('boss@example.com', { header: { alg: 'none' } }) })).status === 401);
const t = (await token('alice@example.com')).split('.');
const forged = [t[0], b64u(JSON.stringify({ aud: ['aud-123'], iss: 'https://team.cloudflareaccess.com', email: 'boss@example.com', exp: 9999999999 })), t[2]].join('.');
check('내용을 바꿔치기한 토큰은 받지 않는다', (await call('/api/me', null, { tok: forged })).status === 401);
_resetCaches();
check('로그인 설정이 비어 있으면 아무도 들이지 않는다',
      (await handle(new Request(site + '/api/me', { headers: { 'Cf-Access-Jwt-Assertion': await token('boss@example.com') } }),
                    { ...env, ACCESS_AUD: '' }, async () => new Response('화면'), fetchFn)).status === 401);

console.log('누구인지');
let r = await call('/api/me', 'boss@example.com');
check('관리자: 주인 계좌의 주인으로 본다', r.status === 200 && r.data.admin === true && r.data.id === 'boss', JSON.stringify(r.data));
r = await call('/api/me', 'Alice@Example.com');
check('참가자: 이메일로 계좌를 찾는다 (대소문자 무시)', r.data.id === 'alice' && r.data.admin === false && r.data.name === '앨리스', JSON.stringify(r.data));
check('GitHub 계정 없이 이름표(id)만 있는 참가자도 된다', (await call('/api/me', 'bob@example.com')).data.id === 'bob');
r = await call('/', 'stranger@example.com');
check('명단에 없는 사람은 로그인해도 들이지 않는다', r.status === 403 && String(r.data).includes('명단에 없습니다') && (await call('/data/accounts/alice.json', 'stranger@example.com')).status === 403);
check('파일 이름이 될 수 없는 계정은 계좌로 치지 않는다', (await call('/api/me', 'evil@example.com')).status === 403);

console.log('무엇을 볼 수 있나');
check('참가자는 자기 계좌 자료를 본다', (r = await call('/data/accounts/alice.json', 'alice@example.com')).status === 200 && r.data.account === '앨리스');
check('참가자는 남의 계좌 자료를 못 본다', (await call('/data/accounts/boss.json', 'alice@example.com')).status === 403 && (await call('/data/accounts/bob.json', 'alice@example.com')).status === 403);
check('참가자는 전체 수익률·주인 계좌·관리자 화면을 못 본다', (await call('/data/league.json', 'alice@example.com')).status === 403
      && (await call('/data/state.json', 'alice@example.com')).status === 403 && (await call('/admin.html', 'alice@example.com')).status === 403);
check('관리자는 전부 본다', (await call('/data/league.json', 'boss@example.com')).status === 200 && (await call('/data/accounts/alice.json', 'boss@example.com')).status === 200
      && (await call('/admin.html', 'boss@example.com')).data === '화면');
check('정해진 자료 말고는 저장소의 아무것도 내주지 않는다 (설정·장부·경로 장난)', (await call('/data/../config.json', 'boss@example.com')).data === '화면'      // 주소가 /config.json 으로 정리되어 화면 파일 쪽으로 간다 (저장소에서 읽지 않는다)
      && (await call('/data/accounts/..%2F..%2Fconfig.json', 'boss@example.com')).status === 403 && !canRead('/data/roster.json', { admin: true, id: 'boss', main: true }));
check('아직 자료가 없는 계좌는 없다고 답한다', (await call('/data/accounts/bob.json', 'bob@example.com')).status === 404);
check('거래소 화면은 명단에 있는 누구에게나 내준다', (await call('/', 'alice@example.com')).data === '화면');

console.log('주문');
r = await call('/api/order', 'alice@example.com', { method: 'POST', body: { account: 'boss', symbol: 'MU', side: 'buy', qty: 3, hack: { a: 1 }, client_id: 'x' } });
const put = calls.find((c) => c.init.method === 'PUT');
const sent = put ? JSON.parse(Buffer.from(JSON.parse(put.init.body).content, 'base64').toString('utf8')) : {};
check('주문은 로그인한 사람의 창구 폴더에 올라간다 (요청 안의 계좌는 보지 않는다)', r.status === 200 && put && put.url.includes('/contents/inbox/alice/web-')
      && sent.symbol === 'MU' && sent.qty === 3 && !('account' in sent) && !('hack' in sent) && sent.client_id === r.data.client_id && sent.client_id !== 'x', JSON.stringify(sent));
check('다른 사이트에서 몰래 보낸 주문은 받지 않는다', (await call('/api/order', 'alice@example.com', { method: 'POST', body: { symbol: 'MU' }, headers: { Origin: 'https://evil.example' } })).status === 403
      && !calls.some((c) => c.init.method === 'PUT'));
check('정해진 모양이 아닌 주문은 받지 않는다', (await call('/api/order', 'alice@example.com', { method: 'POST', body: [1, 2] })).status === 400
      && (await call('/api/order', 'alice@example.com', { method: 'POST', body: { symbol: 'MU' }, headers: { 'content-type': 'text/plain' } })).status === 400);

console.log('관리');
r = await call('/api/admin', 'alice@example.com', { method: 'POST', body: { action: 'add_player', id: 'carol' } });
check('참가자는 관리 명령을 낼 수 없다', r.status === 403 && !calls.some((c) => c.init.method === 'POST'));
r = await call('/api/admin', 'boss@example.com', { method: 'POST', body: { action: 'add_player', id: 'carol', email: 'carol@example.com', name: '캐럴', extra: 'x' } });
const post = calls.find((c) => c.init.method === 'POST');
const issue = post ? JSON.parse(post.init.body) : {};
check('관리자의 명령은 "[관리]" 이슈로 거래소에 넘어간다', r.status === 200 && issue.title === '[관리] add_player'
      && issue.body.includes('"email":"carol@example.com"') && !issue.body.includes('extra'), JSON.stringify(issue));
check('모르는 관리 명령은 넘기지 않는다', (await call('/api/admin', 'boss@example.com', { method: 'POST', body: { action: 'drop_all' } })).status === 400);
check('명단 판단 (직접)', whoami('nobody@example.com', config, env).id === null && whoami('boss@example.com', config, env).main === true);
r = await call('/api/admin', 'boss@example.com', { method: 'POST', body: { action: 'add_player', id: 'dan', login: 'dan-st' } });
check('참가자를 sharktalk 아이디로도 넣을 수 있다', r.status === 200 && JSON.parse(calls.find((c) => c.init.method === 'POST').init.body).body.includes('"login":"dan-st"'));

console.log('sharktalk 로그인 (인증 워커의 /me 에 쿠키를 넘겨 묻는다)');
// 실제 sharktalk-auth 의 /me: 로그인 됨 = 200 { authenticated: true, user: { email, name, role } }, 안 됨 = 401 { authenticated: false }
const sessions = { 'st_session=boss': { authenticated: true, user: { email: 'Boss@Example.com', name: '주인', role: 'admin' } },
                   'st_session=alice': { authenticated: true, user: { email: 'alice@example.com', name: '앨리스', role: 'editor' } },
                   'st_session=out': { authenticated: false, user: { email: 'boss@example.com' } },
                   'st_session=bare': { email: 'boss@example.com' },
                   'other=boss': { authenticated: true, user: { email: 'boss@example.com' } } };
let asked = [];
const stEnv = { GITHUB_REPO: 'owner/repo', GITHUB_TOKEN: 'tok', ADMIN_EMAILS: 'boss@example.com', LOGIN_URL: 'https://auth.sharktalk.co.kr/login',
  AUTH_SVC: { fetch: async (req) => { asked.push(req.url); const s = sessions[req.headers.get('cookie')]; return s ? Response.json(s) : Response.json({ authenticated: false }, { status: 401 }); } } };
files['config.json'] = { players: [...config.players, { id: 'carl', name: '칼', login: 'carl' }] };
_resetCaches();
const st = async (path, cookie, init = {}) => {
  const res = await handle(new Request(site + path, { ...init, headers: { ...(cookie ? { Cookie: cookie } : {}), ...(init.headers || {}) } }), stEnv, async () => new Response('화면'), fetchFn);
  const text = await res.text(); let data; try { data = JSON.parse(text); } catch (e) { data = text; }
  return { status: res.status, data, headers: res.headers };
};
r = await st('/api/me', 'st_session=boss');
check('sharktalk 에 로그인한 관리자를 알아본다', r.status === 200 && r.data.admin === true && r.data.id === 'boss' && asked.at(-1) === 'https://auth.sharktalk.co.kr/me', JSON.stringify(r.data));
check('sharktalk 에 로그인한 참가자는 자기 계좌만', (await st('/data/accounts/alice.json', 'st_session=alice')).status === 200 && (await st('/data/league.json', 'st_session=alice')).status === 403);
r = await st('/admin.html', null);
check('쿠키가 없으면 들이지 않고, 로그인 화면에 돌아올 주소를 실어 알려 준다', r.status === 401 && !String(r.data).includes('화면')
      && String(r.data).includes('https://auth.sharktalk.co.kr/login?next=' + encodeURIComponent(site + '/admin.html')), String(r.data).slice(-200));
let n0 = asked.length;
check('st_session 쿠키가 없으면 인증 워커에 묻지도 않는다', (await st('/api/me', 'other=boss')).status === 401 && asked.length === n0);
check('인증 워커가 모르는 쿠키·로그인 안 됨 응답은 들이지 않는다', (await st('/api/me', 'st_session=nobody')).status === 401 && (await st('/api/me', 'st_session=out')).status === 401);
check('authenticated 표시가 없는 응답은 로그인으로 보지 않는다', (await st('/api/me', 'st_session=bare')).status === 401);
for (const p of ['/', '/admin.html', '/data/league.json', '/data/state.json', '/data/accounts/alice.json', '/api/me'])
  check('로그인 없이 막힘 ' + p, (await st(p, null)).status === 401);
r = await st('/', 'st_session=alice');
check('통과한 화면은 캐시에 남기지 않는다', r.status === 200 && r.data === '화면' && r.headers.get('cache-control') === 'private, no-store' && r.headers.get('x-robots-tag') === 'noindex, nofollow');
check('참가자에게 관리자 화면은 나가지 않는다', (await st('/admin.html', 'st_session=alice')).status === 403 && (await st('/admin.html', 'st_session=boss')).status === 200);
check('sharktalk 로그인일 때는 Access 토큰을 들고 와도 소용없다', (await handle(new Request(site + '/api/me', { headers: { 'Cf-Access-Jwt-Assertion': await token('boss@example.com') } }),
      { ...stEnv, ACCESS_TEAM: env.ACCESS_TEAM, ACCESS_AUD: env.ACCESS_AUD }, async () => new Response('화면'), fetchFn)).status === 401);
check('/me 응답은 실제 모양 하나만 받는다', identityFromMe({ authenticated: true, user: { email: 'A@b.c', name: 'x', role: 'admin' } }).email === 'a@b.c'
      && identityFromMe({ user: { email: 'a@b.c' } }) === null && identityFromMe({ authenticated: 'yes', user: { email: 'a@b.c' } }) === null
      && identityFromMe({ authenticated: true, user: { email: 'not-an-email' } }) === null && identityFromMe({ authenticated: true, email: 'a@b.c' }) === null
      && identityFromMe({ authenticated: false, user: { email: 'a@b.c' } }) === null && identityFromMe({}) === null && identityFromMe(null) === null);

console.log(`\n${fails.length ? '실패 ' + fails.length + '건' : '전부 통과'}`);
process.exit(fails.length ? 1 : 0);
