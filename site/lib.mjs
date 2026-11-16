// 거래소 화면(exchange.sharktalk.co.kr)의 문지기. site/worker.mjs 가 모든 요청을 여기로 넘긴다.
//
// 하는 일
//   1. 로그인 확인: sharktalk 인증 워커(sharktalk-auth)의 /me 에 쿠키를 넘겨 묻는다 (service binding AUTH_SVC).
//      2026-11-15 sharktalk-auth/index.js 의 실제 코드와 견줘 맞췄다:
//        로그인 쿠키 st_session (Domain=.sharktalk.co.kr — exchange. 에도 온다), 로그인 안 됨 = 401 {authenticated:false},
//        로그인 됨 = 200 {authenticated:true, user:{email,name,role}}. sharktalk 의 "아이디"는 이메일 하나뿐이다.
//        로그인 화면은 https://auth.sharktalk.co.kr/login?next=돌아올주소 (sharktalk 주소만 받는다).
//      AUTH_SVC 가 없고 ACCESS_TEAM·ACCESS_AUD 가 있으면 Cloudflare Access 토큰으로 확인한다 (sharktalk 밖에 올릴 때의 대안).
//   2. 누구인지: 로그인한 사람(이메일 또는 sharktalk 아이디) → 참가자 (자료 저장소 players.json 의 players[] email 또는 login. 없으면 config.json).
//      관리자는 비밀 설정 ADMIN_EMAILS (이메일이나 아이디, 쉼표로 여럿).
//   3. 자료 내주기: /data/... 는 저장소에서 읽어 오되, 자기 계좌 것만. 전체 수익률과 관리자 화면은 관리자만.
//   4. 주문 받기: /api/order → 저장소의 inbox/{계좌}/ 에 요청 파일을 올린다 (거래소의 주문 창구가 접수한다).
//   5. 관리: /api/admin → 자료 저장소의 admin/ 에 요청 파일을 올린다 (거래소의 관리 창구가 처리하고 결과를 data/admin_log.json 에 남긴다).
//   6. 시장 정보(주문 페이지): /api/market 시장 현황, /api/search?q= 종목 검색, /api/quote?symbol= 종목 현황 — market.mjs. 로그인한 참가자 누구나.
//   7. 에이전트 입구 /api/v1/… — sharktalk 로그인 대신 계좌별 열쇠(Authorization: Bearer pxk_…). 열쇠 하나 = 계좌 하나, 자기 계좌만.
//      열쇠는 관리자 화면에서 주인이 만든다(여기서 만들어 한 번만 보여 주고, 명단에는 sha256 지문만 남긴다). 쓰는 법은 에이전트-안내.md.
//
// 설정 (wrangler.jsonc 의 vars·services 와 wrangler secret)
//   AUTH_SVC      sharktalk-auth 워커 (service binding)     AUTH_ME_URL  /me 주소      LOGIN_URL  로그인하러 갈 주소
//   GITHUB_REPO   자료 저장소 hong4137/paper-exchange-data (비공개)   GITHUB_TOKEN 그 저장소의 Contents 읽기/쓰기 토큰 (비밀)
//   ADMIN_EMAILS  관리자의 이메일이나 아이디 (비밀)          GITHUB_BRANCH 기본 main
//
// 이 파일은 거래소의 돈 계산을 하지 않는다. 주문이 맞는지는 거래소(broker.py)가 판단한다.

import * as market from './market.mjs';

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

/** sharktalk-auth 의 /me 응답에서 "누구인가"를 꺼낸다. 로그인하지 않았으면 null.
 *  실제 모양 하나만 받는다: { authenticated: true, user: { email, name, role } }.
 *  authenticated 가 정확히 true 가 아니거나 user.email 이 이메일이 아니면 로그인하지 않은 것으로 본다. */
export function identityFromMe(j) {
  if (!j || typeof j !== 'object' || j.authenticated !== true) return null;
  const u = j.user;
  if (!u || typeof u !== 'object' || typeof u.email !== 'string' || !u.email.includes('@')) return null;
  return { email: u.email.trim().toLowerCase(), login: null };
}

/** sharktalk 로그인 확인: 인증 워커의 /me 에 쿠키를 넘겨 묻는다. 맞으면 { email, login }, 아니면 null. */
export async function verifySharktalk(request, env) {
  const cookie = request.headers.get('Cookie') || '';
  if (!/(?:^|;\s*)st_session=[^;]/.test(cookie) || !env.AUTH_SVC) return null;
  try {
    const r = await env.AUTH_SVC.fetch(new Request(env.AUTH_ME_URL || 'https://auth.sharktalk.co.kr/me',
      { headers: { cookie, accept: 'application/json' } }));
    if (r.status !== 200) return null;
    return identityFromMe(await r.json());
  } catch (e) {
    return null;
  }
}

/** 요청에 실린 Access 토큰을 검증한다. 맞으면 { email }, 아니면 null. (sharktalk 밖에 올릴 때의 대안) */
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
    return { email: String(claims.email).toLowerCase(), login: null };
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
  let r = await repoFile(env, 'players.json', fetchFn);           // 자료 저장소의 명단
  if (r.status === 404) r = await repoFile(env, 'config.json', fetchFn);  // 예전 자리 (한 저장소 시절)
  if (!r.ok) throw new Error('거래소 설정을 읽지 못했습니다');
  cfgCache = { at: Date.now(), cfg: await r.json() };
  return cfgCache.cfg;
}

const accountId = (p) => String(p.id || p.github || '').toLowerCase();
const validId = (s) => /^[a-z0-9][a-z0-9-]{0,38}$/.test(s);

/** 로그인한 사람으로 참가자를 찾는다. who = { email, login }. 반환 { email, login, admin, id, name, main } — 계좌가 없으면 id 는 null.
 *  명단의 email(이메일) 또는 login(sharktalk 아이디)과 맞춰 본다. */
export function whoami(who, cfg, env) {
  if (typeof who === 'string') who = { email: who.toLowerCase(), login: null };
  const mine = [who.email, who.login].filter(Boolean);
  const admins = String(env.ADMIN_EMAILS || '').toLowerCase().split(',').map((x) => x.trim()).filter(Boolean);
  const players = (cfg.players || []).filter((p) => validId(accountId(p)));
  const admin = mine.some((x) => admins.includes(x));
  const low = (v) => String(v || '').toLowerCase();
  let me = players.find((p) => (who.email && low(p.email) === who.email) || (who.login && low(p.login) === who.login));
  if (!me && admin) me = players.find((p) => p.main);          // 관리자는 주인 계좌의 주인이다
  return { email: who.email, login: who.login, admin, id: me ? accountId(me) : null, name: me ? (me.name || accountId(me)) : null, main: !!(me && me.main) };
}

// ---------- 3. 무엇을 볼 수 있나 ----------
/** 이 사람이 이 자료 경로를 읽어도 되는가. 경로는 /data/... */
export function canRead(pathname, me) {
  if (pathname === '/data/demo.json') return true;                       // 화면 확인용 가짜 자료
  const m = /^\/data\/accounts\/([a-z0-9][a-z0-9-]{0,38})\.json$/.exec(pathname);
  if (m) return me.admin || (me.id !== null && me.id === m[1]);          // 자기 계좌만 (관리자는 전부)
  if (pathname === '/data/state.json') return me.admin || me.main;       // 주인 계좌
  if (pathname === '/data/league.json') return me.admin;                 // 전체 수익률
  if (pathname === '/data/admin_log.json') return me.admin;              // 관리 요청의 결과
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

const ADMIN_ACTIONS = { add_player: ['id', 'github', 'email', 'login', 'name', 'agent'], remove_player: ['id', 'github'],
                        add_contest: ['name', 'start', 'end'], remove_contest: ['name'],
                        approve_fork: ['account', 'fork'], reject_fork: ['account', 'fork', 'why'],
                        set_key: ['id', 'hash', 'label'], revoke_key: ['id'],
                        approve_application: ['id', 'account'], reject_application: ['id', 'why'], clear_login: ['id'] };

/** 관리 명령을 자료 저장소의 admin/ 에 요청 파일로 올린다 (관리자만 부른다 — handle 이 확인한다). */
export async function submitAdmin(body, env, fetchFn = fetch, now = new Date()) {
  const keys = ADMIN_ACTIONS[body.action];
  if (!keys) return { ok: false, status: 400 };
  const req = { action: body.action };
  for (const k of keys) if (typeof body[k] === 'string' && body[k].trim()) req[k] = body[k].trim().slice(0, 80);
  req.requested_at = now.toISOString();
  const stamp = now.toISOString().replace(/[-:.TZ]/g, '').slice(0, 17);
  const rand = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, '0')).join('');
  const r = await gh(env, `contents/admin/${stamp}-${rand}.json`, { method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message: `관리 요청 ${req.action}`, branch: branch(env),
                           content: bytesToB64(te.encode(JSON.stringify(req))) }) }, fetchFn);
  if (!r.ok) return { ok: false, status: r.status };
  return { ok: true };
}

// ---------- 들어오는 요청 한 건 ----------
const deny = (status, msg) => new Response(
  `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>모의 거래소</title>` +
  `<body style="font-family:system-ui,sans-serif;background:#0b1120;color:#e8edf7;padding:40px 20px;text-align:center"><p>${msg}</p></body>`,
  { status, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });

// ---------- 7. 에이전트 입구 (/api/v1) ----------
const KEY_RE = /^pxk_[A-Za-z0-9]{32,64}$/;
const CID_RE = /^[A-Za-z0-9._:-]{1,60}$/;
const V1_KEYS = ['action', 'order', 'why', 'ref', 'symbol', 'side', 'type', 'qty', 'krw', 'usd', 'price', 'session', 'valid_days',
                 'when', 'value', 'watch', 'dry_run'];
const rate = new Map();                                   // 열쇠 지문 → [분, 횟수] (워커 하나 안에서만 — 대략의 막이)
const RATE_PER_MIN = 60;

async function sha256hex(text) {
  const d = await crypto.subtle.digest('SHA-256', te.encode(text));
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** 새 에이전트 열쇠 — 평문(한 번만 보여 준다)과 지문. */
export async function newAgentKey() {
  const abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const raw = crypto.getRandomValues(new Uint8Array(40));
  const key = 'pxk_' + Array.from(raw, (b) => abc[b % abc.length]).join('');
  return { key, hash: await sha256hex(key) };
}

/** 열쇠로 계좌를 찾는다. 반환 {id, name} 또는 null. */
export async function agentFromKey(request, cfg) {
  const m = /^Bearer\s+(\S+)$/.exec(request.headers.get('Authorization') || '');
  if (!m || !KEY_RE.test(m[1])) return null;
  const h = await sha256hex(m[1]);
  const p = (cfg.players || []).find((x) => (x.api_keys || []).some((k) => k.hash === h) && validId(accountId(x)));
  return p ? { id: accountId(p), name: p.name || accountId(p), hash: h } : null;
}

function cleanRequest(body) {
  const req = {};
  for (const k of V1_KEYS) {
    const v = body[k];
    if (v === undefined || v === null || v === '') continue;
    if (typeof v === 'string') req[k] = v.slice(0, k === 'why' ? 200 : 80);
    else if (typeof v === 'number' && Number.isFinite(v)) req[k] = v;
    else if (typeof v === 'boolean') req[k] = v;
  }
  if (body.action === 'fork') {                           // 분기 요청의 논거 글 (거래소가 다시 자른다)
    const a = body.arguments;
    if (typeof a === 'string') req.arguments = a.slice(0, 6000);
    else if (a && typeof a === 'object' && !Array.isArray(a))
      req.arguments = Object.fromEntries(Object.entries(a).slice(0, 5).filter(([, v]) => typeof v === 'string').map(([k, v]) => [k.slice(0, 40), v.slice(0, 6000)]));
  }
  return req;
}

async function readJsonFile(env, path, fetchFn) {
  const r = await repoFile(env, path, fetchFn);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error('read');
  return r.json();
}

/** 요청 번호로 결과를 찾는다: 접수됨(주문·취소·지켜보기·분기) / 받지 않음 / 검사만 / 아직 창구에 / 모름. */
export function requestStatus(cid, acct, checks, queued) {
  const ch = (checks || []).find((x) => x.client_id === cid);
  if (ch) return { client_id: cid, status: 'checked', result: ch };
  const rf = (acct?.refused || []).find((x) => x.client_id === cid);
  if (rf) return { client_id: cid, status: 'refused', why: rf.why, at: rf.ts };
  const od = (acct?.orders || []).find((x) => x.client_id === cid);
  if (od) return { client_id: cid, status: 'accepted', action: 'order', order: od };
  const cn = (acct?.orders || []).find((x) => x.result && x.result.client_id === cid);
  if (cn) return { client_id: cid, status: 'accepted', action: 'cancel', order: cn };
  const w = (acct?.watches || []).find((x) => x.client_id === cid);
  if (w) return { client_id: cid, status: 'accepted', action: 'watch', watch: w };
  const f = (acct?.forks || []).find((x) => x.client_id === cid);
  if (f) return { client_id: cid, status: 'accepted', action: 'fork', fork: f };
  return { client_id: cid, status: queued ? 'queued' : 'unknown' };
}

// ---------- 참가 신청 (열쇠 없이) ----------
// POST /api/v1/apply {real_name(신청한 사람의 실명, 필수), name(화면 이름), agent, id(바라는 이름표), email, message}
//   → 자료 저장소 applications/pending/{신청 번호}.json, 답은 202 {application, claim(찾아갈 번호 — 한 번만 보여 준다)}
// GET  /api/v1/apply/{신청 번호} + Authorization: Bearer pxc_… (찾아갈 번호)
//   → pending / rejected(why) / approved: 처음 한 번만 에이전트 열쇠(pxk_)를 내준다 (그때 만들어 지문만 거래소에 보낸다)
const APP_RE = /^ap-[0-9]{17}-[0-9a-f]{8}$/;
const CLAIM_RE = /^pxc_[A-Za-z0-9]{32,64}$/;
const APPLY_MAX_PENDING = 20, APPLY_PER_HOUR = 5;
const applyRate = new Map();                              // 보낸 곳(IP) → [시, 횟수] — 워커 하나 안에서 대략

async function randomToken(prefix) {
  const abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return prefix + Array.from(crypto.getRandomValues(new Uint8Array(40)), (b) => abc[b % abc.length]).join('');
}

async function handleApply(request, env, fetchFn, url) {
  const path = url.pathname;
  if (path === '/api/v1/apply' && request.method === 'POST') {
    const ip = request.headers.get('CF-Connecting-IP') || 'x';
    const hour = Math.floor(Date.now() / 3600000);
    const [h0, n0] = applyRate.get(ip) || [hour, 0];
    const n = h0 === hour ? n0 + 1 : 1;
    applyRate.set(ip, [hour, n]);
    if (n > APPLY_PER_HOUR) return json({ error: '신청이 너무 잦습니다. 한 시간 뒤에 다시 해 주세요.' }, 429);
    if (!/^application\/json/i.test(request.headers.get('content-type') || '')) return json({ error: 'JSON 으로 보내 주세요' }, 400);
    const text = await request.text();
    if (text.length > 4000) return json({ error: '신청이 너무 깁니다' }, 400);
    let b; try { b = JSON.parse(text); } catch (e) { b = null; }
    if (!b || typeof b !== 'object' || Array.isArray(b)) return json({ error: '신청 내용을 읽을 수 없습니다' }, 400);
    const str = (v, max) => (typeof v === 'string' ? v.trim().slice(0, max) : '');
    const app = { real_name: str(b.real_name, 30), name: str(b.name, 30), agent: str(b.agent, 40), want_id: str(b.id, 20).toLowerCase(),
                  email: str(b.email, 120).toLowerCase(), message: str(b.message, 300) };
    if (app.real_name.length < 2) return json({ error: '신청한 사람의 실명(real_name)을 적어 주세요' }, 400);
    if (!app.name) return json({ error: '화면에 나올 이름(name)을 적어 주세요' }, 400);
    if (app.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(app.email)) return json({ error: '이메일 모양이 올바르지 않습니다' }, 400);
    if (app.want_id && !/^[a-z][a-z0-9-]{1,19}$/.test(app.want_id)) return json({ error: '바라는 이름표(id)는 영문 소문자로 시작하는 영문·숫자·- 20자까지입니다' }, 400);
    const list = await gh(env, `contents/applications/pending?ref=${encodeURIComponent(branch(env))}`, {}, fetchFn);
    if (list.ok && (await list.json()).filter((x) => /\.json$/.test(x.name)).length >= APPLY_MAX_PENDING)
      return json({ error: '기다리는 신청이 많습니다. 주인이 정리한 뒤 다시 해 주세요.' }, 503);
    const now = new Date();
    const stamp = now.toISOString().replace(/[-:.TZ]/g, '').slice(0, 17);
    const id = `ap-${stamp}-${Array.from(crypto.getRandomValues(new Uint8Array(4)), (x) => x.toString(16).padStart(2, '0')).join('')}`;
    const claim = await randomToken('pxc_');
    const rec = { id, ...Object.fromEntries(Object.entries(app).filter(([, v]) => v)), claim_hash: await sha256hex(claim), applied_at: now.toISOString(), status: 'pending' };
    const r = await gh(env, `contents/applications/pending/${id}.json`, { method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message: `참가 신청 ${id}`, branch: branch(env), content: bytesToB64(te.encode(JSON.stringify(rec, null, 1))) }) }, fetchFn);
    if (!r.ok) return json({ error: '거래소에 전하지 못했습니다. 잠시 뒤 다시 해 주세요.' }, 502);
    return json({ ok: true, application: id, claim, status: 'pending',
                  message: '신청을 받았습니다. 찾아갈 번호(claim)는 지금 한 번만 보여 줍니다 — 잘 두세요. 주인이 수락하면 GET /api/v1/apply/{application} 에 Authorization: Bearer {claim} 을 붙여 열쇠를 받아 갑니다.' }, 202);
  }
  const m = /^\/api\/v1\/apply\/(ap-[0-9]{17}-[0-9a-f]{8})$/.exec(path);
  if (m && request.method === 'GET') {
    const auth = /^Bearer\s+(\S+)$/.exec(request.headers.get('Authorization') || '');
    if (!auth || !CLAIM_RE.test(auth[1])) return json({ error: '찾아갈 번호가 없거나 맞지 않습니다 (Authorization: Bearer pxc_…)' }, 401);
    const h = await sha256hex(auth[1]);
    let rec = null, where = null, sha = null;
    for (const kind of ['pending', 'done']) {
      const r = await gh(env, `contents/applications/${kind}/${m[1]}.json?ref=${encodeURIComponent(branch(env))}`, {}, fetchFn);
      if (r.ok) { const j = await r.json(); rec = JSON.parse(new TextDecoder().decode(b64uToBytes(j.content.replace(/\n/g, '')))); where = kind; sha = j.sha; break; }
    }
    if (!rec || rec.claim_hash !== h) return json({ error: '신청 번호나 찾아갈 번호가 맞지 않습니다' }, 401);
    if (rec.status === 'pending' || where === 'pending') return json({ application: rec.id, status: 'pending', message: '주인이 아직 정하지 않았습니다. 나중에 다시 물어 주세요.' });
    if (rec.status === 'rejected') return json({ application: rec.id, status: 'rejected', why: rec.why || '' });
    if (rec.claimed_at) return json({ application: rec.id, status: 'approved', account: rec.account, claimed: true,
                                      message: '열쇠는 이미 받아 갔습니다. 잃었으면 주인에게 새로 받으세요.' });
    const k = await newAgentKey();
    const done = { ...rec, claimed_at: new Date().toISOString() };
    const w = await gh(env, `contents/applications/done/${rec.id}.json`, { method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message: `열쇠 받아 감 ${rec.id}`, branch: branch(env), sha, content: bytesToB64(te.encode(JSON.stringify(done, null, 1))) }) }, fetchFn);
    if (!w.ok) return json({ error: '열쇠를 내주지 못했습니다. 잠시 뒤 다시 해 주세요.' }, w.status === 409 ? 409 : 502);
    const r = await submitAdmin({ action: 'set_key', id: rec.account, hash: k.hash, label: '신청 ' + rec.id }, env, fetchFn);
    if (!r.ok) return json({ error: '열쇠를 거래소에 알리지 못했습니다. 주인에게 알려 주세요.' }, 502);
    return json({ application: rec.id, status: 'approved', account: rec.account, key: k.key,
                  message: '에이전트 열쇠입니다. 지금 한 번만 보여 줍니다. 1~2분 뒤부터 쓸 수 있습니다 — 쓰는 법은 에이전트-안내.md.' });
  }
  return json({ error: '없는 주소이거나 보내는 방식이 다릅니다' }, 404);
}

async function handleAgent(request, env, fetchFn, url) {
  const path = url.pathname;
  if (path === '/api/v1/apply' || path.startsWith('/api/v1/apply/')) return handleApply(request, env, fetchFn, url);
  let cfg;
  try { cfg = await loadConfig(env, fetchFn); } catch (e) { return json({ error: '거래소 자료를 읽지 못했습니다' }, 502); }
  const ag = await agentFromKey(request, cfg);
  if (!ag) return json({ error: '열쇠가 없거나 맞지 않습니다 (Authorization: Bearer pxk_…)' }, 401);
  const minute = Math.floor(Date.now() / 60000);
  const [m0, n0] = rate.get(ag.hash) || [minute, 0];
  const n = m0 === minute ? n0 + 1 : 1;
  rate.set(ag.hash, [minute, n]);
  if (n > RATE_PER_MIN) return json({ error: `요청이 너무 많습니다 (1분에 ${RATE_PER_MIN}번까지)` }, 429);
  const get = request.method === 'GET';
  try {
    if (path === '/api/v1/account' && get) {
      const a = await readJsonFile(env, `docs/data/accounts/${ag.id}.json`, fetchFn);
      return a ? json(a) : json({ error: '아직 계좌 자료가 없습니다 (계좌를 연 뒤 첫 정기 실행에서 생깁니다)' }, 404);
    }
    if (path === '/api/v1/requests' && request.method === 'POST') {
      if (!/^application\/json/i.test(request.headers.get('content-type') || '')) return json({ error: 'JSON 으로 보내 주세요' }, 400);
      const text = await request.text();
      if (text.length > 40000) return json({ error: '요청이 너무 깁니다' }, 400);
      let body; try { body = JSON.parse(text); } catch (e) { body = null; }
      if (!body || typeof body !== 'object' || Array.isArray(body)) return json({ error: '요청 내용을 읽을 수 없습니다' }, 400);
      const req = cleanRequest(body);
      const now = new Date();
      if (typeof body.client_id === 'string' && !CID_RE.test(body.client_id)) return json({ error: 'client_id 는 영문·숫자·._:- 60자까지입니다' }, 400);
      const stamp = now.toISOString().replace(/[-:.TZ]/g, '').slice(0, 17);
      const rand = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, '0')).join('');
      req.client_id = body.client_id || `api-${stamp}-${rand}`;
      req.requested_at = now.toISOString();
      const file = `inbox/${ag.id}/${req.client_id.replace(/:/g, '_')}.json`;
      const r = await gh(env, `contents/${file}`, { method: 'PUT', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: `요청 ${ag.id}`, branch: branch(env), content: bytesToB64(te.encode(JSON.stringify(req))) }) }, fetchFn);
      if (r.status === 422) return json({ error: '같은 client_id 의 요청이 아직 창구에 있습니다' }, 409);
      if (!r.ok) return json({ error: '거래소에 전하지 못했습니다. 잠시 뒤 다시 보내 주세요.' }, 502);
      return json({ ok: true, client_id: req.client_id, status: 'queued',
                    message: '창구에 올렸습니다. 보통 20~60초 뒤 /api/v1/requests/{client_id} 에서 결과를 볼 수 있습니다.' }, 202);
    }
    const rm = /^\/api\/v1\/requests\/([A-Za-z0-9._:-]{1,60})$/.exec(path);
    if (rm && get) {
      const cid = rm[1];
      const [acct, checks, q] = await Promise.all([
        readJsonFile(env, `docs/data/accounts/${ag.id}.json`, fetchFn),
        readJsonFile(env, `docs/data/checks/${ag.id}.json`, fetchFn),
        repoFile(env, `inbox/${ag.id}/${cid.replace(/:/g, '_')}.json`, fetchFn)]);
      return json(requestStatus(cid, acct, checks, q.ok));
    }
    if (get && (path === '/api/v1/market' || path === '/api/v1/search' || path === '/api/v1/quote')) {
      if (path === '/api/v1/market') return json(await market.overview(fetchFn));
      if (path === '/api/v1/search') return json(await market.search(url.searchParams.get('q'), fetchFn));
      return json(await market.quote(url.searchParams.get('symbol'), fetchFn));
    }
  } catch (e) {
    return json({ error: /올바르지|아닙니다/.test(String(e.message)) ? e.message : '자료를 읽지 못했습니다. 잠시 뒤 다시 해 주세요.' }, 502);
  }
  return json({ error: '없는 주소이거나 보내는 방식이 다릅니다' }, 404);
}

// ---------- 거래소 자체 로그인 (열쇠로) ----------
// 사람도 그 계좌의 열쇠(pxk_…)로 /login 에서 들어온다. 문지기가 열쇠 지문을 명단과 맞춰 보고
// 거래소 주소에만 붙는 세션 쿠키(px_session, HttpOnly·Secure·SameSite=Lax, Domain 없음 — sharktalk 다른 서비스와 나누지 않는다)를 준다.
// 쿠키 = base64url({id, k: 열쇠 지문 앞 16자, exp}).서명 — 서명 열쇠는 GITHUB_TOKEN 에서 끌어낸 HMAC (새 비밀값이 필요 없다).
// 열쇠를 새로 만들거나 끊으면 지문이 달라져 그 세션도 끝난다. 관리자 = 주인 계좌("main")의 열쇠로 들어온 사람.
const SESSION = 'px_session';
const SESSION_DAYS = 30;
const loginRate = new Map();                             // 보낸 곳(IP) → [시, 횟수]
const b64u = (bytes) => bytesToB64(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

async function sessionKey(env) {
  const raw = await crypto.subtle.digest('SHA-256', te.encode('px-session:' + (env.GITHUB_TOKEN || '')));
  return crypto.subtle.importKey('raw', raw, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
}

export async function makeSession(env, id, keyHash, now = Date.now()) {
  const body = b64u(te.encode(JSON.stringify({ id, k: keyHash.slice(0, 16), exp: now + SESSION_DAYS * 86400000 })));
  const sig = new Uint8Array(await crypto.subtle.sign('HMAC', await sessionKey(env), te.encode(body)));
  return `${body}.${b64u(sig)}`;
}

/** 쿠키의 세션을 확인한다. 반환 {id, k} 또는 null. */
export async function readSession(request, env, now = Date.now()) {
  const m = /(?:^|;\s*)px_session=([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)/.exec(request.headers.get('Cookie') || '');
  if (!m) return null;
  try {
    const ok = await crypto.subtle.verify('HMAC', await sessionKey(env), b64uToBytes(m[2]), te.encode(m[1]));
    if (!ok) return null;
    const p = JSON.parse(new TextDecoder().decode(b64uToBytes(m[1])));
    return p && p.exp > now && typeof p.id === 'string' && typeof p.k === 'string' ? p : null;
  } catch (e) { return null; }
}

/** 세션 → 거래소 사람. 열쇠가 바뀌었으면 null. */
function meFromSession(sess, cfg) {
  const p = (cfg.players || []).find((x) => accountId(x) === sess.id && validId(accountId(x)));
  if (!p || !(p.api_keys || []).some((k) => String(k.hash).startsWith(sess.k))) return null;
  return { email: null, login: null, admin: !!p.main, id: accountId(p), name: p.name || accountId(p), main: !!p.main };
}

const cookie = (val, maxAge) => `${SESSION}=${val}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;

async function handleLogin(request, env, fetchFn, url) {
  if (url.pathname === '/logout' || url.pathname === '/api/logout') {
    return new Response(null, { status: 303, headers: { Location: '/login', 'Set-Cookie': cookie('', 0), 'cache-control': 'no-store' } });
  }
  // POST /api/login {key}
  const ip = request.headers.get('CF-Connecting-IP') || 'x';
  const hour = Math.floor(Date.now() / 3600000);
  const [h0, n0] = loginRate.get(ip) || [hour, 0];
  const n = h0 === hour ? n0 + 1 : 1;
  loginRate.set(ip, [hour, n]);
  if (n > 20) return json({ error: '시도가 너무 많습니다. 한 시간 뒤에 다시 해 주세요.' }, 429);
  if (!sameOrigin(request)) return json({ error: '이 화면에서 보낸 요청이 아닙니다' }, 403);
  const body = await readBody(request);
  const key = body && typeof body.key === 'string' ? body.key.trim() : '';
  if (!KEY_RE.test(key)) return json({ error: '열쇠 모양이 아닙니다 (pxk_ 로 시작합니다)' }, 400);
  let cfg;
  try { cfg = await loadConfig(env, fetchFn); } catch (e) { return json({ error: '거래소 자료를 읽지 못했습니다' }, 502); }
  const ag = await agentFromKey(new Request(url, { headers: { Authorization: `Bearer ${key}` } }), cfg);
  if (!ag) return json({ error: '맞는 열쇠가 아닙니다' }, 401);
  const sess = await makeSession(env, ag.id, ag.hash);
  return new Response(JSON.stringify({ ok: true, id: ag.id, name: ag.name }), { status: 200,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'Set-Cookie': cookie(sess, SESSION_DAYS * 86400) } });
}

/** next: 정적 파일(화면)을 그대로 내주는 함수. */
export async function handle(request, env, next, fetchFn = fetch) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (path.startsWith('/api/v1/')) return handleAgent(request, env, fetchFn, url);   // 에이전트는 로그인 대신 열쇠
  if (path === '/api/login' && request.method === 'POST') return handleLogin(request, env, fetchFn, url);
  if (path === '/logout' || path === '/api/logout') return handleLogin(request, env, fetchFn, url);
  if ((path === '/apply' || path === '/apply.html' || path === '/login' || path === '/login.html') && request.method === 'GET') {   // 참가 원서·로그인 — 로그인 없이 열리는 화면
    const res = await next();
    const headers = new Headers(res.headers);
    headers.set('cache-control', 'no-store');
    headers.set('x-robots-tag', 'noindex, nofollow');
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
  }
  const api = path.startsWith('/api/') || path.startsWith('/data/');
  const sess = await readSession(request, env);
  // (옮겨 가는 동안만) 거래소 열쇠 세션이 없으면 예전 sharktalk 로그인도 본다 — 주인이 자기 열쇠를 만들 수 있게. 다음 단계에서 걷어 낸다.
  const who = sess ? null : (env.AUTH_SVC ? await verifySharktalk(request, env) : await verifyAccess(request, env, fetchFn));
  const needLogin = () => {
    const back = encodeURIComponent(url.pathname + (url.search || ''));
    return api ? json({ error: '로그인이 필요합니다' }, 401)
               : deny(401, `로그인이 필요합니다. <a style="color:#f2c14e" href="/login?next=${back}">열쇠로 들어가기</a>`);
  };
  if (!sess && !who) return needLogin();
  let cfg;
  try { cfg = await loadConfig(env, fetchFn); } catch (e) {
    return api ? json({ error: '거래소 자료를 읽지 못했습니다' }, 502) : deny(502, '거래소 자료를 읽지 못했습니다. 잠시 뒤 다시 열어 주세요.');
  }
  const me = sess ? meFromSession(sess, cfg) : whoami(who, cfg, env);
  if (!me) return needLogin();                            // 열쇠가 바뀌었거나 끊겼다
  if (!me.admin && me.id === null) {
    return api ? json({ error: '참가자 명단에 없는 계정입니다' }, 403)
               : deny(403, `${(who && (who.email || who.login)) || '이 계정'} 은(는) 참가자 명단에 없습니다. <a style="color:#f2c14e" href="/logout">다른 열쇠로 들어가기</a>`);
  }

  if (path === '/api/me') return json({ id: me.id, name: me.name, admin: me.admin, email: me.email });

  if (path === '/api/order' || path === '/api/admin') {
    if (request.method !== 'POST') return json({ error: '보내는 방식이 올바르지 않습니다' }, 405);
    if (!sameOrigin(request)) return json({ error: '이 화면에서 보낸 요청이 아닙니다' }, 403);
    const body = await readBody(request);
    if (!body) return json({ error: '요청 내용을 읽을 수 없습니다' }, 400);
    if (path === '/api/admin') {
      if (!me.admin) return json({ error: '관리자만 할 수 있습니다' }, 403);
      if (body.action === 'issue_key') {                  // 열쇠는 여기서 만들어 주인에게 한 번만 보여 준다 — 거래소에는 지문만 간다
        const id = String(body.id || '').trim().toLowerCase();
        if (!validId(id)) return json({ error: '이름표를 적어 주세요' }, 400);
        const k = await newAgentKey();
        const r = await submitAdmin({ action: 'set_key', id, hash: k.hash, label: String(body.label || '') }, env, fetchFn);
        if (!r.ok) return json({ error: '거래소에 전하지 못했습니다' }, 502);
        cfgCache = { at: 0, cfg: null };
        return json({ ok: true, key: k.key, message: `${id} 의 열쇠입니다. 지금 한 번만 보여 줍니다 — 복사해 두세요. 1~2분 뒤부터 쓸 수 있고, 예전 열쇠는 끊깁니다.` });
      }
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

  if (path === '/api/market' || path === '/api/search' || path === '/api/quote') {
    if (request.method !== 'GET') return json({ error: '보내는 방식이 올바르지 않습니다' }, 405);
    try {
      if (path === '/api/market') return json(await market.overview(fetchFn));
      if (path === '/api/search') return json(await market.search(url.searchParams.get('q'), fetchFn));
      return json(await market.quote(url.searchParams.get('symbol'), fetchFn));
    } catch (e) {
      return json({ error: /올바르지|아닙니다/.test(String(e.message)) ? e.message : '시세를 받지 못했습니다. 잠시 뒤 다시 해 주세요.' }, 502);
    }
  }

  if (path.startsWith('/api/')) return json({ error: '없는 주소입니다' }, 404);
  if ((path === '/admin.html' || path === '/admin') && !me.admin) return deny(403, '관리자만 볼 수 있는 화면입니다.');
  // 로그인한 사람에게만 나가는 화면이다 — 중간 캐시에 남기지 않고 검색에 걸리지 않게 (sharktalk 공용 문지기와 같은 머리말)
  const res = await next();
  const headers = new Headers(res.headers);
  headers.set('cache-control', 'private, no-store');
  headers.set('x-robots-tag', 'noindex, nofollow');
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}
