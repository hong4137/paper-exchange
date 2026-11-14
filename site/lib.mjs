// 로그인 있는 화면(Cloudflare Pages + Access)의 문지기. functions/_middleware.js 가 모든 요청을 여기로 넘긴다.
//
// 하는 일
//   1. 로그인 확인: Cloudflare Access 가 붙여 주는 서명된 토큰을 검증하고 이메일을 꺼낸다.
//   2. 누구인지: 이메일 → 참가자 (비공개 저장소의 config.json players[].email), 관리자는 환경변수 ADMIN_EMAILS.
//   3. 자료 내주기: /data/... 는 저장소에서 읽어 오되, 자기 계좌 것만. 전체 수익률과 관리자 화면은 관리자만.
//   4. 주문 받기: /api/order → 저장소의 inbox/{계좌}/ 에 요청 파일을 올린다 (거래소의 주문 창구가 접수한다).
//   5. 관리: /api/admin → 저장소에 "[관리]" 이슈를 연다 (거래소가 주인 계정의 이슈로 처리한다).
//
// 환경변수 (Cloudflare Pages 설정)
//   ACCESS_TEAM   예: myteam.cloudflareaccess.com        ACCESS_AUD   Access 애플리케이션의 Audience 값
//   GITHUB_REPO   예: hong4137/paper-exchange            GITHUB_TOKEN 그 저장소의 Contents·Issues 읽기/쓰기 토큰 (비밀)
//   ADMIN_EMAILS  관리자 이메일 (쉼표로 여럿)             GITHUB_BRANCH 기본 main
//
// 이 파일은 거래소의 돈 계산을 하지 않는다. 주문이 맞는지는 거래소(broker.py)가 판단한다.

const te = new TextEncoder();
const b64uToBytes = (s) => {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(s + '='.repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
};
const bytesToB64 = (bytes) => { let s = ''; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };
const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
const teamHost = (env) => String(env.ACCESS_TEAM || '').replace(/^https?:\/\//, '').replace(/\/+$/, '');

// ---------- 1. 로그인 확인 ----------
let certCache = { at: 0, keys: null };
async function accessKeys(env, fetchFn) {
  if (certCache.keys && Date.now() - certCache.at < 10 * 60 * 1000) return certCache.keys;
  const r = await fetchFn(`https://${teamHost(env)}/cdn-cgi/access/certs`);
  if (!r.ok) throw new Error('로그인 확인용 열쇠를 받지 못했습니다');
  certCache = { at: Date.now(), keys: (await r.json()).keys || [] };
  return certCache.keys;
}
export function _resetCaches() { certCache = { at: 0, keys: null }; cfgCache = { at: 0, cfg: null }; }

/** 요청에 실린 Access 토큰을 검증한다. 맞으면 { email }, 아니면 null. */
export async function verifyAccess(request, env, fetchFn = fetch, now = Date.now()) {
  if (!env.ACCESS_TEAM || !env.ACCESS_AUD) return null;      // 설정이 없으면 아무도 들이지 않는다
  let token = request.headers.get('Cf-Access-Jwt-Assertion');
  if (!token) {
    const m = /(?:^|;\s*)CF_Authorization=([^;]+)/.exec(request.headers.get('Cookie') || '');
    token = m && m[1];
  }
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  try {
    const header = JSON.parse(new TextDecoder().decode(b64uToBytes(parts[0])));
    const claims = JSON.parse(new TextDecoder().decode(b64uToBytes(parts[1])));
    if (header.alg !== 'RS256') return null;
    const jwk = (await accessKeys(env, fetchFn)).find((k) => k.kid === header.kid);
    if (!jwk) return null;
    const key = await crypto.subtle.importKey('jwk', { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: 'RS256', ext: true },
      { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
    const ok = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64uToBytes(parts[2]), te.encode(`${parts[0]}.${parts[1]}`));
    if (!ok) return null;
    const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    if (!aud.includes(env.ACCESS_AUD)) return null;
    if (claims.iss !== `https://${teamHost(env)}`) return null;
    if (!claims.exp || claims.exp * 1000 <= now) return null;
    if (!claims.email) return null;
    return { email: String(claims.email).toLowerCase() };
  } catch (e) {
    return null;
  }
}

// ---------- 2. 누구인지 ----------
const gh = (env, path, init = {}, fetchFn = fetch) => fetchFn(`https://api.github.com/repos/${env.GITHUB_REPO}/${path}`, {
  ...init,
  headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, 'user-agent': 'paper-exchange-site',
             accept: 'application/vnd.github+json', 'x-github-api-version': '2022-11-28', ...(init.headers || {}) } });
const branch = (env) => env.GITHUB_BRANCH || 'main';

async function repoFile(env, path, fetchFn) {
  const r = await gh(env, `contents/${path}?ref=${encodeURIComponent(branch(env))}`,
    { headers: { accept: 'application/vnd.github.raw+json' } }, fetchFn);
  return r;
}

let cfgCache = { at: 0, cfg: null };
async function loadConfig(env, fetchFn) {
  if (cfgCache.cfg && Date.now() - cfgCache.at < 60 * 1000) return cfgCache.cfg;
  const r = await repoFile(env, 'config.json', fetchFn);
  if (!r.ok) throw new Error('거래소 설정을 읽지 못했습니다');
  cfgCache = { at: Date.now(), cfg: await r.json() };
  return cfgCache.cfg;
}

const accountId = (p) => String(p.id || p.github || '').toLowerCase();
const validId = (s) => /^[a-z0-9][a-z0-9-]{0,38}$/.test(s);

/** 이메일로 참가자를 찾는다. 반환 { email, admin, id, name, main } — 계좌가 없으면 id 는 null. */
export function whoami(email, cfg, env) {
  const admins = String(env.ADMIN_EMAILS || '').toLowerCase().split(',').map((x) => x.trim()).filter(Boolean);
  const players = (cfg.players || []).filter((p) => validId(accountId(p)));
  const admin = admins.includes(email);
  let me = players.find((p) => String(p.email || '').toLowerCase() === email);
  if (!me && admin) me = players.find((p) => p.main);          // 관리자는 주인 계좌의 주인이다
  return { email, admin, id: me ? accountId(me) : null, name: me ? (me.name || accountId(me)) : null, main: !!(me && me.main) };
}

// ---------- 3. 무엇을 볼 수 있나 ----------
/** 이 사람이 이 자료 경로를 읽어도 되는가. 경로는 /data/... */
export function canRead(pathname, me) {
  if (pathname === '/data/demo.json') return true;                       // 화면 확인용 가짜 자료
  const m = /^\/data\/accounts\/([a-z0-9][a-z0-9-]{0,38})\.json$/.exec(pathname);
  if (m) return me.admin || (me.id !== null && me.id === m[1]);          // 자기 계좌만 (관리자는 전부)
  if (pathname === '/data/state.json') return me.admin || me.main;       // 주인 계좌
  if (pathname === '/data/league.json') return me.admin;                 // 전체 수익률
  return false;                                                          // 그 밖의 자료는 내주지 않는다
}

// ---------- 4·5. 주문과 관리 ----------
const ORDER_KEYS = ['action', 'order', 'why', 'ref', 'symbol', 'side', 'type', 'qty', 'krw', 'usd', 'price', 'session', 'valid_days'];

function sameOrigin(request) {
  const origin = request.headers.get('Origin');
  if (!origin) return false;
  try { return new URL(origin).host === new URL(request.url).host; } catch (e) { return false; }
}

async function readBody(request) {
  if (!/^application\/json/i.test(request.headers.get('content-type') || '')) return null;
  const text = await request.text();
  if (text.length > 4000) return null;
  try { const v = JSON.parse(text); return v && typeof v === 'object' && !Array.isArray(v) ? v : null; } catch (e) { return null; }
}

/** 주문 요청을 저장소의 inbox/{계좌}/ 에 올린다. 계좌는 로그인한 사람의 것 — 요청 안의 계좌는 보지 않는다. */
export async function submitOrder(body, me, env, fetchFn = fetch, now = new Date()) {
  const req = {};
  for (const k of ORDER_KEYS) {
    const v = body[k];
    if (v === undefined || v === null || v === '') continue;
    if (typeof v === 'string') req[k] = v.slice(0, 80);
    else if (typeof v === 'number' && Number.isFinite(v)) req[k] = v;
  }
  const stamp = now.toISOString().replace(/[-:.TZ]/g, '').slice(0, 17);
  const rand = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, '0')).join('');
  req.client_id = `web-${stamp}-${rand}`;
  req.requested_at = now.toISOString();
  const path = `inbox/${me.id}/${req.client_id}.json`;
  const r = await gh(env, `contents/${path}`, { method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message: `주문 요청 ${me.id}`, branch: branch(env),
                           content: bytesToB64(te.encode(JSON.stringify(req))) }) }, fetchFn);
  if (!r.ok) return { ok: false, status: r.status };
  return { ok: true, client_id: req.client_id };
}

const ADMIN_ACTIONS = { add_player: ['id', 'github', 'email', 'name', 'agent'], remove_player: ['id', 'github'],
                        add_contest: ['name', 'start', 'end'], remove_contest: ['name'] };

/** 관리 명령을 저장소의 "[관리]" 이슈로 넘긴다. 이슈는 토큰 주인(거래소 주인)의 이름으로 열린다. */
export async function submitAdmin(body, env, fetchFn = fetch) {
  const keys = ADMIN_ACTIONS[body.action];
  if (!keys) return { ok: false, status: 400 };
  const req = { action: body.action };
  for (const k of keys) if (typeof body[k] === 'string' && body[k].trim()) req[k] = body[k].trim().slice(0, 80);
  const r = await gh(env, 'issues', { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title: `[관리] ${req.action}`, body: '```json\n' + JSON.stringify(req) + '\n```' }) }, fetchFn);
  if (!r.ok) return { ok: false, status: r.status };
  return { ok: true };
}

// ---------- 들어오는 요청 한 건 ----------
const deny = (status, msg) => new Response(
  `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>모의 거래소</title>` +
  `<body style="font-family:system-ui,sans-serif;background:#0b1120;color:#e8edf7;padding:40px 20px;text-align:center"><p>${msg}</p></body>`,
  { status, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });

/** next: 정적 파일(화면)을 그대로 내주는 함수. */
export async function handle(request, env, next, fetchFn = fetch) {
  const url = new URL(request.url);
  const path = url.pathname;
  const api = path.startsWith('/api/') || path.startsWith('/data/');
  const who = await verifyAccess(request, env, fetchFn);
  if (!who) return api ? json({ error: '로그인이 필요합니다' }, 401) : deny(401, '로그인이 필요합니다. 주소를 다시 열어 로그인해 주세요.');
  let cfg;
  try { cfg = await loadConfig(env, fetchFn); } catch (e) {
    return api ? json({ error: '거래소 자료를 읽지 못했습니다' }, 502) : deny(502, '거래소 자료를 읽지 못했습니다. 잠시 뒤 다시 열어 주세요.');
  }
  const me = whoami(who.email, cfg, env);
  if (!me.admin && me.id === null) {
    return api ? json({ error: '참가자 명단에 없는 계정입니다' }, 403)
               : deny(403, `${who.email} 은(는) 참가자 명단에 없습니다. 거래소 주인에게 초대를 요청해 주세요.`);
  }

  if (path === '/api/me') return json({ id: me.id, name: me.name, admin: me.admin, email: me.email });

  if (path === '/api/order' || path === '/api/admin') {
    if (request.method !== 'POST') return json({ error: '보내는 방식이 올바르지 않습니다' }, 405);
    if (!sameOrigin(request)) return json({ error: '이 화면에서 보낸 요청이 아닙니다' }, 403);
    const body = await readBody(request);
    if (!body) return json({ error: '요청 내용을 읽을 수 없습니다' }, 400);
    if (path === '/api/admin') {
      if (!me.admin) return json({ error: '관리자만 할 수 있습니다' }, 403);
      const r = await submitAdmin(body, env, fetchFn);
      if (r.ok) cfgCache = { at: 0, cfg: null };               // 명단이 곧 바뀐다 — 다음 요청 때 다시 읽는다
      return r.ok ? json({ ok: true, message: '관리 요청을 보냈습니다. 1~2분 뒤에 반영됩니다.' })
                  : json({ error: r.status === 400 ? '모르는 관리 명령입니다' : '거래소에 전하지 못했습니다' }, r.status === 400 ? 400 : 502);
    }
    if (me.id === null) return json({ error: '계좌가 없습니다' }, 403);
    const r = await submitOrder(body, me, env, fetchFn);
    return r.ok ? json({ ok: true, client_id: r.client_id, message: '주문 요청을 보냈습니다. 1~2분 뒤 전표에 나타납니다.' })
                : json({ error: '거래소에 전하지 못했습니다. 잠시 뒤 다시 내 주세요.' }, 502);
  }

  if (path.startsWith('/data/')) {
    if (request.method !== 'GET') return json({ error: '보내는 방식이 올바르지 않습니다' }, 405);
    if (!canRead(path, me)) return json({ error: '볼 수 없는 자료입니다' }, 403);
    const r = await repoFile(env, `docs${path}`, fetchFn);
    if (r.status === 404) return json({ error: '아직 자료가 없습니다' }, 404);
    if (!r.ok) return json({ error: '거래소 자료를 읽지 못했습니다' }, 502);
    return new Response(r.body, { status: 200, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
  }

  if (path.startsWith('/api/')) return json({ error: '없는 주소입니다' }, 404);
  if ((path === '/admin.html' || path === '/admin') && !me.admin) return deny(403, '관리자만 볼 수 있는 화면입니다.');
  return next();
}
