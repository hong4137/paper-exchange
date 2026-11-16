// 거래소 화면(exchange.sharktalk.co.kr)의 문지기. site/worker.mjs 가 모든 요청을 여기로 넘긴다.
//
// 로그인은 거래소 자체의 것이다 (사용자 결정 2026-11-16: "샤크토크를 섞으면 어떻게 해" — sharktalk 로그인은 쓰지 않는다).
//   계좌 열쇠(pxk_…)로 /login → 이 주소에만 붙는 세션 쿠키(px_session). 관리자 = 주인 계좌("main")의 열쇠로 들어온 사람.
//   에이전트는 쿠키 없이 같은 열쇠를 Authorization: Bearer 로 /api/v1/… 에 붙인다.
//
// 하는 일
//   1. 로그인 (/login, /api/login, /logout) — 열쇠 지문을 명단(players.json players[].api_keys)과 맞춰 본다.
//   2. 자료 내주기: /data/... 는 저장소에서 읽어 오되, 자기 계좌 것만. 전체 수익률과 관리자 화면은 관리자만.
//   3. 주문 받기: /api/order → 저장소의 inbox/{계좌}/ 에 요청 파일을 올린다 (거래소의 주문 창구가 접수한다).
//   4. 관리: /api/admin → 자료 저장소의 admin/ 에 요청 파일을 올린다 (결과는 data/admin_log.json).
//   5. 시장 정보: /api/market·search·quote — market.mjs.
//   6. 에이전트 입구 /api/v1/… — 계좌별 열쇠. 참가 원서 /apply·/api/v1/apply (로그인 없이). 쓰는 법은 에이전트-안내.md.
//
// 설정 (wrangler.jsonc 의 vars 와 wrangler secret)
//   GITHUB_REPO   자료 저장소 hong4137/paper-exchange-data (비공개)   GITHUB_TOKEN 그 저장소의 Contents 읽기/쓰기 토큰 (비밀 — 세션 서명에도 쓴다)
//   GITHUB_BRANCH 기본 main
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
export function _resetCaches() { cfgCache = { at: 0, cfg: null }; }
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
                        set_key: ['id', 'hash', 'label'], revoke_key: ['id'], set_password: ['id', 'password', 'label'],
                        approve_application: ['id', 'account'], reject_application: ['id', 'why'], clear_login: ['id'] };

/** 관리 명령을 자료 저장소의 admin/ 에 요청 파일로 올린다 (관리자만 부른다 — handle 이 확인한다). */
export async function submitAdmin(body, env, fetchFn = fetch, now = new Date()) {
  const keys = ADMIN_ACTIONS[body.action];
  if (!keys) return { ok: false, status: 400 };
  const req = { action: body.action };
  for (const k of keys) if (typeof body[k] === 'string' && body[k].trim()) req[k] = body[k].trim().slice(0, k === 'password' ? 200 : 80);
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
// POST /api/v1/apply {real_name(신청한 사람의 실명, 필수), name(화면 이름), agent, id(바라는 이름표), message}
//   → 자료 저장소 applications/pending/{신청 번호}.json, 답은 202 {application, claim(찾아갈 번호 — 한 번만 보여 준다)}
// GET  /api/v1/apply/{신청 번호} + Authorization: Bearer pxc_… (찾아갈 번호)
//   → pending / rejected(why) / approved: 처음 한 번만 에이전트 열쇠(pxk_)를 내준다 (그때 만들어 지문만 거래소에 보낸다)
// ---------- 참가 원서 (/api/v1/apply — 로그인 없이) ----------
// 원서에 아이디·비밀번호를 함께 받는다. 비밀번호는 여기서 PBKDF2 로 바꾼 값만 자료 저장소에 둔다.
// 주인이 수락하면 그 아이디·비밀번호로 /login 에 바로 들어온다. 에이전트 열쇠는 들어온 뒤 "내 설정"에서 만든다.
const APPLY_MAX_PENDING = 20, APPLY_PER_HOUR = 5;
const applyRate = new Map();                              // 보낸 곳(IP) → [시, 횟수] — 워커 하나 안에서 대략
export const LOGIN_ID_RE = /^[a-z][a-z0-9-]{1,19}$/;

async function pendingApps(env, fetchFn) {
  const list = await gh(env, `contents/applications/pending?ref=${encodeURIComponent(branch(env))}`, {}, fetchFn);
  if (!list.ok) return [];
  const names = (await list.json()).filter((x) => /\.json$/.test(x.name)).map((x) => x.name);
  const out = [];
  for (const n of names) { const a = await readJsonFile(env, `applications/pending/${n}`, fetchFn); if (a) out.push(a); }
  return out;
}

async function handleApply(request, env, fetchFn, url) {
  if (url.pathname !== '/api/v1/apply' || request.method !== 'POST') return json({ error: '없는 주소이거나 보내는 방식이 다릅니다' }, 404);
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
                message: str(b.message, 300) };
  const pw = typeof b.password === 'string' ? b.password : '';
  if (app.real_name.length < 2) return json({ error: '신청한 사람의 실명(real_name)을 적어 주세요' }, 400);
  if (!app.name) return json({ error: '화면에 나올 이름(name)을 적어 주세요' }, 400);
  if (!LOGIN_ID_RE.test(app.want_id)) return json({ error: '아이디(id)는 영문 소문자로 시작하는 영문 소문자·숫자·- 2~20자입니다' }, 400);
  const bad = pwProblem(pw);
  if (bad) return json({ error: bad }, 400);
  let cfg;
  try { cfg = await loadConfig(env, fetchFn); } catch (e) { return json({ error: '거래소 자료를 읽지 못했습니다' }, 502); }
  const pend = await pendingApps(env, fetchFn);
  if (pend.length >= APPLY_MAX_PENDING) return json({ error: '기다리는 신청이 많습니다. 주인이 정리한 뒤 다시 해 주세요.' }, 503);
  if ((cfg.players || []).some((p) => accountId(p) === app.want_id) || pend.some((a) => a.want_id === app.want_id) || /^(p|f)[0-9]+$/.test(app.want_id))
    return json({ error: '그 아이디는 이미 쓰이고 있습니다. 다른 아이디를 골라 주세요.' }, 409);
  const now = new Date();
  const stamp = now.toISOString().replace(/[-:.TZ]/g, '').slice(0, 17);
  const id = `ap-${stamp}-${Array.from(crypto.getRandomValues(new Uint8Array(4)), (x) => x.toString(16).padStart(2, '0')).join('')}`;
  const rec = { id, ...Object.fromEntries(Object.entries(app).filter(([, v]) => v)), password: await hashPassword(pw), applied_at: now.toISOString(), status: 'pending' };
  const r = await gh(env, `contents/applications/pending/${id}.json`, { method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message: `참가 신청 ${id}`, branch: branch(env), content: bytesToB64(te.encode(JSON.stringify(rec, null, 1))) }) }, fetchFn);
  if (!r.ok) return json({ error: '거래소에 전하지 못했습니다. 잠시 뒤 다시 해 주세요.' }, 502);
  return json({ ok: true, application: id, id: app.want_id, status: 'pending',
                message: '신청을 받았습니다. 주인이 수락하면 이 아이디와 비밀번호로 /login 에 들어오고, "내 설정"에서 에이전트 열쇠를 만듭니다.' }, 202);
}

async function handleAgent(request, env, fetchFn, url) {
  const path = url.pathname;
  if (path === '/api/v1/apply' || path.startsWith('/api/v1/apply/')) return handleApply(request, env, fetchFn, url);   // 예전 찾아가기 주소는 404
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

// ---------- 거래소 자체 로그인 (아이디·비밀번호) ----------
// 아이디 = 계좌 이름표. 비밀번호는 PBKDF2-SHA256(10만 번, 소금 16바이트)으로 바꾼 값만 명단(players[].password)에 둔다 — 원문은 어디에도 남지 않는다.
// 들어오면 거래소 주소에만 붙는 세션 쿠키(px_session, HttpOnly·Secure·SameSite=Lax, Domain 없음 — sharktalk 다른 서비스와 나누지 않는다)를 준다.
// 쿠키 = base64url({id, k: 비밀번호 지문 끝 16자, exp}).서명 — 서명 열쇠는 GITHUB_TOKEN 에서 끌어낸 HMAC (새 비밀값이 필요 없다).
// 비밀번호가 바뀌면 그 세션은 끝난다. 관리자 = 주인 계좌("main")로 들어온 사람.
// 예전 열쇠 로그인({key})도 받는다 — 비밀번호를 아직 정하지 않은 계좌, 비밀번호를 잃었을 때의 뒷문.
const SESSION = 'px_session';
const SESSION_DAYS = 30;
const PW_ITER = 100000;                                  // Cloudflare Workers 의 PBKDF2 상한
const loginRate = new Map();                             // 보낸 곳(IP) → [시, 횟수]
const b64u = (bytes) => bytesToB64(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

export function pwProblem(pw) {
  if (typeof pw !== 'string' || pw.length < 8) return '비밀번호는 8자 이상으로 정해 주세요';
  if (pw.length > 100) return '비밀번호가 너무 깁니다 (100자까지)';
  return null;
}

async function pbkdf2(pw, salt, iter) {
  const k = await crypto.subtle.importKey('raw', te.encode(pw), 'PBKDF2', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: iter }, k, 256));
}

/** 비밀번호 → 'pbkdf2$반복$소금$지문' */
export async function hashPassword(pw) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  return `pbkdf2$${PW_ITER}$${b64u(salt)}$${b64u(await pbkdf2(pw, salt, PW_ITER))}`;
}

export async function checkPassword(pw, stored) {
  const m = /^pbkdf2\$(\d+)\$([A-Za-z0-9_-]+)\$([A-Za-z0-9_-]+)$/.exec(String(stored || ''));
  if (!m || typeof pw !== 'string') return false;
  const got = b64u(await pbkdf2(pw, b64uToBytes(m[2]), Number(m[1])));
  let diff = got.length ^ m[3].length;
  for (let i = 0; i < Math.min(got.length, m[3].length); i++) diff |= got.charCodeAt(i) ^ m[3].charCodeAt(i);
  return diff === 0;
}

/** 읽기 쉬운 임시 비밀번호 (헷갈리는 글자 0·O·1·l·I 는 뺀다). */
export function tempPassword() {
  const abc = 'abcdefghijkmnpqrstuvwxyz23456789';
  return Array.from(crypto.getRandomValues(new Uint8Array(10)), (b) => abc[b % abc.length]).join('').replace(/^(.{5})/, '$1-');
}

const pwTag = (stored) => String(stored || '').slice(-16);

async function sessionKey(env) {
  const raw = await crypto.subtle.digest('SHA-256', te.encode('px-session:' + (env.GITHUB_TOKEN || '')));
  return crypto.subtle.importKey('raw', raw, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
}

/** tag: 비밀번호 지문 끝 16자, 또는 (열쇠로 들어왔으면) 열쇠 지문 앞 16자. */
export async function makeSession(env, id, tag, now = Date.now()) {
  const body = b64u(te.encode(JSON.stringify({ id, k: tag.slice(0, 16), exp: now + SESSION_DAYS * 86400000 })));
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

/** 세션 → 거래소 사람. 비밀번호(또는 들어올 때 쓴 열쇠)가 바뀌었으면 null. */
function meFromSession(sess, cfg) {
  const p = (cfg.players || []).find((x) => accountId(x) === sess.id && validId(accountId(x)));
  if (!p) return null;
  const ok = (p.password && pwTag(p.password) === sess.k) || (p.api_keys || []).some((k) => String(k.hash).startsWith(sess.k));
  if (!ok) return null;
  return { email: null, login: null, admin: !!p.main, id: accountId(p), name: p.name || accountId(p), main: !!p.main,
           has_password: !!p.password, has_key: !!(p.api_keys || []).length };
}

const cookie = (val, maxAge) => `${SESSION}=${val}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
const withCookie = (obj, sess) => new Response(JSON.stringify(obj), { status: 200,
  headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'Set-Cookie': cookie(sess, SESSION_DAYS * 86400) } });

async function handleLogin(request, env, fetchFn, url) {
  if (url.pathname === '/logout' || url.pathname === '/api/logout') {
    return new Response(null, { status: 303, headers: { Location: '/login', 'Set-Cookie': cookie('', 0), 'cache-control': 'no-store' } });
  }
  // POST /api/login {id, password} (또는 예전 {key})
  const ip = request.headers.get('CF-Connecting-IP') || 'x';
  const hour = Math.floor(Date.now() / 3600000);
  const [h0, n0] = loginRate.get(ip) || [hour, 0];
  const n = h0 === hour ? n0 + 1 : 1;
  loginRate.set(ip, [hour, n]);
  if (n > 20) return json({ error: '시도가 너무 많습니다. 한 시간 뒤에 다시 해 주세요.' }, 429);
  if (!sameOrigin(request)) return json({ error: '이 화면에서 보낸 요청이 아닙니다' }, 403);
  const body = await readBody(request);
  if (!body) return json({ error: '요청 내용을 읽을 수 없습니다' }, 400);
  let cfg;
  try { cfg = await loadConfig(env, fetchFn); } catch (e) { return json({ error: '거래소 자료를 읽지 못했습니다' }, 502); }
  if (typeof body.key === 'string' && body.key.trim()) {
    const key = body.key.trim();
    if (!KEY_RE.test(key)) return json({ error: '열쇠 모양이 아닙니다 (pxk_ 로 시작합니다)' }, 400);
    const ag = await agentFromKey(new Request(url, { headers: { Authorization: `Bearer ${key}` } }), cfg);
    if (!ag) return json({ error: '맞는 열쇠가 아닙니다' }, 401);
    return withCookie({ ok: true, id: ag.id, name: ag.name }, await makeSession(env, ag.id, ag.hash));
  }
  const id = typeof body.id === 'string' ? body.id.trim().toLowerCase() : '';
  const pw = typeof body.password === 'string' ? body.password : '';
  if (!id || !pw) return json({ error: '아이디와 비밀번호를 넣어 주세요' }, 400);
  const p = (cfg.players || []).find((x) => accountId(x) === id && validId(accountId(x)));
  if (p && p.password && await checkPassword(pw, p.password))
    return withCookie({ ok: true, id, name: p.name || id }, await makeSession(env, id, pwTag(p.password)));
  if (!p) {                                               // 아직 수락 전인 원서인지 알려 준다 (비밀번호가 맞을 때만)
    const a = (await pendingApps(env, fetchFn)).find((x) => x.want_id === id);
    if (a && await checkPassword(pw, a.password)) return json({ error: '주최자가 아직 원서를 수락하지 않았습니다. 수락되면 이 아이디와 비밀번호로 들어올 수 있습니다.' }, 403);
  }
  return json({ error: '아이디나 비밀번호가 맞지 않습니다' }, 401);
}

/** next: 정적 파일(화면)을 그대로 내주는 함수. */
export async function handle(request, env, next, fetchFn = fetch) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (path.startsWith('/api/v1/')) return handleAgent(request, env, fetchFn, url);   // 에이전트는 로그인 대신 열쇠
  if (path === '/api/login' && request.method === 'POST') return handleLogin(request, env, fetchFn, url);
  if (path === '/logout' || path === '/api/logout') return handleLogin(request, env, fetchFn, url);
  if (path === '/agents' && request.method === 'GET') return new Response(null, { status: 301, headers: { Location: '/agents.md' } });
  if (path === '/agents.md' && request.method === 'GET') {           // 에이전트 안내 — 로그인 없이 (원본은 저장소의 에이전트-안내.md, 올릴 때 복사)
    const res = await next();
    const headers = new Headers(res.headers);
    headers.set('content-type', 'text/markdown; charset=utf-8');
    headers.set('cache-control', 'public, max-age=300');
    headers.set('x-robots-tag', 'noindex');
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
  }
  if ((path === '/apply' || path === '/apply.html' || path === '/login' || path === '/login.html') && request.method === 'GET') {   // 참가 원서·로그인 — 로그인 없이 열리는 화면
    const res = await next();
    const headers = new Headers(res.headers);
    headers.set('cache-control', 'no-store');
    headers.set('x-robots-tag', 'noindex, nofollow');
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
  }
  const api = path.startsWith('/api/') || path.startsWith('/data/');
  const sess = await readSession(request, env);
  const needLogin = () => {
    const back = encodeURIComponent(url.pathname + (url.search || ''));
    return api ? json({ error: '로그인이 필요합니다' }, 401)
               : deny(401, `로그인이 필요합니다. <a style="color:#f2c14e" href="/login?next=${back}">들어가기</a><script>location.replace('/login?next=${back}')</script>`);
  };
  if (!sess) return needLogin();
  let cfg;
  try { cfg = await loadConfig(env, fetchFn); } catch (e) {
    return api ? json({ error: '거래소 자료를 읽지 못했습니다' }, 502) : deny(502, '거래소 자료를 읽지 못했습니다. 잠시 뒤 다시 열어 주세요.');
  }
  const me = meFromSession(sess, cfg);
  if (!me) return needLogin();                            // 열쇠가 바뀌었거나 끊겼다

  if (path === '/api/me') return json({ id: me.id, name: me.name, admin: me.admin, has_password: me.has_password, has_key: me.has_key });

  if (path === '/api/password' || path === '/api/key') {   // 내 설정: 비밀번호 바꾸기 · 에이전트 열쇠 만들기 (자기 계좌만)
    if (request.method !== 'POST') return json({ error: '보내는 방식이 올바르지 않습니다' }, 405);
    if (!sameOrigin(request)) return json({ error: '이 화면에서 보낸 요청이 아닙니다' }, 403);
    const body = (await readBody(request)) || {};
    if (path === '/api/password') {
      const p = (cfg.players || []).find((x) => accountId(x) === me.id);
      if (p && p.password && !(await checkPassword(String(body.current || ''), p.password))) return json({ error: '지금 비밀번호가 맞지 않습니다' }, 403);
      const bad = pwProblem(body.password);
      if (bad) return json({ error: bad }, 400);
      const hashed = await hashPassword(body.password);
      const r = await submitAdmin({ action: 'set_password', id: me.id, password: hashed }, env, fetchFn);
      if (!r.ok) return json({ error: '거래소에 전하지 못했습니다' }, 502);
      cfgCache = { at: 0, cfg: null };
      // 비밀번호가 있던 계좌는 명단이 바뀌는 순간(1~2분 뒤) 지금 세션이 끝난다 — 화면이 새 비밀번호로 다시 들어오라고 안내한다
      return json({ ok: true, relogin: !!(p && p.password),
                    message: p && p.password ? '비밀번호를 바꿨습니다. 1~2분 뒤 새 비밀번호로 다시 들어와 주세요.'
                                             : '비밀번호를 정했습니다. 1~2분 뒤부터 아이디 ' + me.id + ' 와 이 비밀번호로 들어옵니다.' });
    }
    const k = await newAgentKey();
    const r = await submitAdmin({ action: 'set_key', id: me.id, hash: k.hash, label: '내 설정' }, env, fetchFn);
    if (!r.ok) return json({ error: '거래소에 전하지 못했습니다' }, 502);
    cfgCache = { at: 0, cfg: null };
    return json({ ok: true, key: k.key, account: me.id, message: '에이전트 열쇠입니다. 지금 한 번만 보여 줍니다. 1~2분 뒤부터 쓸 수 있고, 예전 열쇠는 끊깁니다.' });
  }

  if (path === '/api/order' || path === '/api/admin') {
    if (request.method !== 'POST') return json({ error: '보내는 방식이 올바르지 않습니다' }, 405);
    if (!sameOrigin(request)) return json({ error: '이 화면에서 보낸 요청이 아닙니다' }, 403);
    const body = await readBody(request);
    if (!body) return json({ error: '요청 내용을 읽을 수 없습니다' }, 400);
    if (path === '/api/admin') {
      if (!me.admin) return json({ error: '관리자만 할 수 있습니다' }, 403);
      if (body.action === 'reset_password') {             // 임시 비밀번호 — 주인에게 한 번만 보여 주고, 거래소에는 지문만 간다
        const id = String(body.id || '').trim().toLowerCase();
        if (!validId(id)) return json({ error: '이름표를 적어 주세요' }, 400);
        const pw = tempPassword();
        const r = await submitAdmin({ action: 'set_password', id, password: await hashPassword(pw), label: 'reset' }, env, fetchFn);
        if (!r.ok) return json({ error: '거래소에 전하지 못했습니다' }, 502);
        cfgCache = { at: 0, cfg: null };
        return json({ ok: true, password: pw, message: `${id} 의 임시 비밀번호입니다. 지금 한 번만 보여 줍니다. 1~2분 뒤부터 아이디 ${id} 와 이 비밀번호로 들어오고, 들어와서 "내 설정"에서 바꾸면 됩니다.` });
      }
      if (body.action === 'set_password') return json({ error: '비밀번호는 "비밀번호 새로 만들기"로 바꿉니다' }, 400);
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
